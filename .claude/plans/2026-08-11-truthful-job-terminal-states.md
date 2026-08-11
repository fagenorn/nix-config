# Truthful Job Terminal States Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A `codex-companion` status read probes the recorded worker pid of active jobs, persists the dead-pid→`failed` transition (removing a reviewer job's runtime directory in the same locked scope), so `status`, `status --wait`, and every downstream consumer see the truth — delivered entirely as a regenerated `patches/agent-plugins/codex-plugin-cc.patch` at `patchRevision = 4`.

**Architecture:** All code changes live in the upstream `openai/codex-plugin-cc` checkout at pinned revision `db52e28f4d9ded852ab3942cea316258ae4ef346`, edited in a scratch clone and landed in this repo only as a regenerated zero-context patch. The liveness probe goes in `lib/process.mjs`, a lock-guarded job-record read-modify-write is exported from `lib/state.mjs`, the dead-worker transition (probe → locked re-check → reviewer cleanup → failed write → log line) lives in `lib/tracked-jobs.mjs`, and the two status snapshot builders in `lib/job-control.mjs` invoke it. Design authority: `.claude/specs/2026-08-10-truthful-job-terminal-states-design.md` — this plan implements it, it does not redesign it.

**Tech stack:** Node.js ≥ 22 ESM (`.mjs`, stdlib only), `node --test` runner, git-generated unified diff patch, Nix (`just build` applies the patch via `patch -p1` inside `lib/agent-plugins.nix`).

## Global Constraints

- Pinned upstream revision: `db52e28f4d9ded852ab3942cea316258ae4ef346` (`openai/codex-plugin-cc`); the flake input never changes.
- The patch file `patches/agent-plugins/codex-plugin-cc.patch` is the only code artifact; never commit the scratch checkout; never edit anything under `/nix/store` (read-only).
- `patchRevision` in `lib/agent-plugins.nix` goes `3` → `4` exactly once (Task 1), never higher.
- The committed patch is zero-context; regenerate with `git diff -U0 <pinned-rev>` and apply with `git apply --unidiff-zero` (plain `git apply` fails on zero-context hunks; nix's `patch -p1` handles them by line number).
- Error text, exact: `Worker process <pid> exited without recording a result.` (`<pid>` interpolated; trailing period included).
- Probe eligibility: `status ∈ {queued, running}` AND `Number.isFinite(pid)`. Probe: `process.kill(pid, 0)`; only `ESRCH` means dead — success, `EPERM`, or any other error means alive.
- Flipped record shape: `status: "failed"`, `phase: "failed"`, `pid: null`, `completedAt` = detection time, `updatedAt` stamped by the guarded write. No new fields (no `failedAt`).
- A metadata-lock timeout during the flip propagates — no catch-and-mute.
- The upstream test `status --wait times out cleanly when a job is still active` (pid-less running record stays running) must stay green — it enshrines the probe-eligibility boundary.
- Canonical test command (from the scratch checkout root; the `env -u` scrub removes this repo's live Claude-session variables which otherwise fail 4 upstream tests spuriously):
  `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
  Baseline at patch p3 (verified 2026-08-11, node v22.22.2): `# tests 96 / # pass 92 / # fail 0 / # skipped 4`.
- `just build` (run in the worktree) is the repo verification step; it must end green in every task that touches the patch.
- Worktree: `/Users/anis/tmp/nix-config/.claude/worktrees/issue-2-truthful-job-states` (branch `worktree-issue-2-truthful-job-states`). Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Scratch checkout workflow (used by every task)

The scratch checkout lives at a fixed path outside the repo and is rebuilt deterministically at the start of every task from the currently committed patch, so tasks are independent and a half-edited scratch tree can never leak between implementers:

```bash
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-2-truthful-job-states
SCRATCH=/tmp/codex-plugin-cc-issue-2-scratch
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346

if [ ! -d "$SCRATCH/.git" ]; then
  gh repo clone openai/codex-plugin-cc "$SCRATCH"
fi
git -C "$SCRATCH" reset --hard
git -C "$SCRATCH" checkout --force --detach "$PIN"
git -C "$SCRATCH" clean -ffd
test -z "$(git -C "$SCRATCH" status --porcelain)"   # must print nothing / exit 0
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
```

Regeneration (end of every task, after tests are green — `add -N` first so files created since setup, e.g. `tests/liveness.test.mjs`, appear in the diff):

```bash
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```

Known one-time churn on the first regeneration (Task 1): the committed patch carries a stale blob hash on the new-file header for `plugins/codex/agents/codex-reviewer.md` (`index 0000000..ab0aa35` becomes `index 0000000..ce1552b`). The file content is unchanged; `patch -p1` and `git apply` ignore index lines. Do not try to suppress this line.

## File structure

Scratch checkout (all paths relative to `$SCRATCH`):

- `plugins/codex/scripts/lib/process.mjs` — gains `isProcessAlive(pid)` (Task 1). Already owns ESRCH-aware process handling.
- `plugins/codex/scripts/lib/state.mjs` — gains `updateJobRecord(cwd, jobId, mutate)`, a lock-guarded single-record read-modify-write reusing the module-private `withMetadataLock` + `atomicWriteFile` (Task 1).
- `plugins/codex/scripts/lib/tracked-jobs.mjs` — gains `reconcileWorkerLiveness(workspaceRoot, job)`, the dead-worker transition (Task 1); Task 3 adds the reviewer-runtime cleanup inside its locked callback.
- `plugins/codex/scripts/lib/job-control.mjs` — `buildSingleJobSnapshot` invokes the reconciliation (Task 1); `buildStatusSnapshot` invokes it for surfaced records (Task 2).
- `tests/liveness.test.mjs` — new behavior-named test file (created Task 1, extended Tasks 2–3).

Repo worktree:

- `patches/agent-plugins/codex-plugin-cc.patch` — regenerated in every task.
- `lib/agent-plugins.nix` — `patchRevision = 3` → `4` (Task 1 only).

## Test seams

Inherited from the spec — implementers test at these and nowhere else:

1. **CLI subprocess surface:** `node <SCRIPT> status … --json` run against a temp workspace; assert the JSON payload.
2. **On-disk state contract:** job record JSON + job log under the workspace's jobs dir, and the reviewer runtime directory, located via the exported resolvers (`resolveStateDir`, `resolveReviewerRuntimeHome`).

Real detached `node -e "setInterval(() => {}, 1000)"` sleeper processes provide live/dead pids (cancel-test precedent). No call-count assertions, no mocking of internal modules, no unit tests of the probe in `tests/process.test.mjs`.

## Auto-resolved decisions

### Task granularity: three behavior slices
- **Question:** One task for the whole change, or several — and along which boundary?
- **Choice:** Three tasks: (1) dead-pid→failed flip on single-job status reads (probe + guarded RMW + transition + `buildSingleJobSnapshot` wiring), (2) listing reconciliation + `--wait` termination, (3) reviewer-runtime cleanup on the flip path. Each ends in a green suite, a regenerated patch, and a worktree commit.
- **Grounding:** writing-plans right-sizing — a reviewer can reject the listing wiring or the cleanup while approving the core transition; each slice maps to distinct acceptance criteria (AC1 single-read / AC1-listing+AC2 / AC3).
- **Alternative considered:** One monolithic task — rejected: no intermediate reviewer gate, and a single failure rolls back ~300 lines of test+code. A fourth plumbing-only task (probe + RMW with no caller) — rejected: its only gate ("suite still green") is already true at base, the definition of a no-op task.

### Scratch checkout at a fixed /tmp path, rebuilt per task
- **Question:** Where does the scratch upstream checkout live, and does it persist between tasks?
- **Choice:** Fixed path `/tmp/codex-plugin-cc-issue-2-scratch`; every task starts with `reset --hard` + `checkout --force --detach <pin>` + `clean -ffd` + apply the currently committed patch. Reuse of the clone is a network optimization only; correctness never depends on prior task state.
- **Grounding:** Dispatch brief permits "/tmp scratch, never committed"; each task's input state is exactly the committed patch, so rebuild-from-patch makes tasks order-independent and self-healing after a crashed task.
- **Alternative considered:** mktemp-fresh clone per task (network-dependent every task, no gain over reset) and a git-ignored dir inside the worktree (risks accidental commit; nothing in `.gitignore` currently covers it).

### Patch regenerated with `git diff -U0`; applied with `--unidiff-zero`
- **Question:** The spec's verification loop says `git apply` + `git diff <rev>`; the committed patch is zero-context, so plain `git apply` rejects it and a default-context `git diff` would rewrite every hunk. Which form is canonical?
- **Choice:** Apply with `git apply --unidiff-zero`; regenerate with `git diff -U0 <pin>`.
- **Grounding:** Verified 2026-08-11: plain `git apply` fails on the committed p3 patch ("patch does not apply", zero-context hunks like `@@ -230 +229,0 @@`); GNU `patch -p1` (what `lib/agent-plugins.nix` runs) applies it cleanly; `git diff -U0` against the pin reproduces the committed patch byte-for-byte except one stale index-line hash. `-U0` keeps patch churn minimal and matches the artifact's established style.
- **Alternative considered:** Regenerating with default `-U3` context — rejected: rewrites all ~1500 patch lines for zero behavioral gain and breaks the byte-stable regen check.

### Suite invocation: `node --test tests/*.test.mjs` with env scrub
- **Question:** The spec/issue write the gate as `node --test tests/`. Is that the command implementers run?
- **Choice:** `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`, run from `$SCRATCH`.
- **Grounding:** Verified 2026-08-11 on node v22.22.2: `node --test tests/` fails (the runner treats the directory as a single entry module — MODULE_NOT_FOUND); upstream's own `package.json` test script is `node --test tests/*.test.mjs`. The scrub is required because this repo's Claude Code session exports the three variables, which spuriously fail 4 upstream tests (verified: 4 fail unscrubbed, 0 fail scrubbed at base). The intent — full suite passes — is unchanged.
- **Alternative considered:** `npm test` — same command via a package-manager indirection; rejected as an extra moving part. Fixing the 4 tests' env handling upstream — out of scope (upstream contribution excluded by the spec).

### patchRevision bumped in Task 1, not the final task
- **Question:** When does `patchRevision` go 3→4, given three patch-touching commits?
- **Choice:** Task 1 bumps it together with the first regenerated patch; Tasks 2–3 leave it at 4. The final task's gate re-verifies `patchRevision = 4` and that the built closure carries a `.p4` plugin path.
- **Grounding:** `codexVersion` embeds `p${patchRevision}`; bumping at the first content change keeps every intermediate commit's version string truthful (the-bar "Truthful terminal states" applied to version metadata). AC5 requires one bump total, which this satisfies.
- **Alternative considered:** Bumping in the last task — rejected: Tasks 1–2 would ship p3-labelled builds containing p4 content.

### `just build` gates every task, not only the final one
- **Question:** Is a green `just build` required per task or once at the end?
- **Choice:** Every task that commits a regenerated patch ends with a green `just build`.
- **Grounding:** CLAUDE.md: "After editing any `.nix`, run `just build` before claiming success" — the patch feeds a nix derivation, so a patch edit is materially a nix-input edit. After the first build the closure is cached; the only rebuilt derivation is the cheap `runCommand` (cp + patch + jq), so the marginal cost is seconds.
- **Alternative considered:** Final-task-only (the brief's minimum) — rejected: an intermediate commit with a nix-unappliable patch would be discovered two tasks late.

### Identifier choices
- **Question:** The spec says module names are binding but identifiers are indicative — which names?
- **Choice:** `isProcessAlive(pid)` (process.mjs), `updateJobRecord(cwd, jobId, mutate)` (state.mjs), `reconcileWorkerLiveness(workspaceRoot, job)` + module-private `isWorkerProbeEligible(job)` (tracked-jobs.mjs).
- **Grounding:** the-bar "name for intent": `updateJobRecord` parallels the existing `updateState`/`upsertJob` family; `reconcileWorkerLiveness` uses the spec's own vocabulary ("reconcile … active records") and names the domain operation, not the mechanism.
- **Alternative considered:** `failJobIfWorkerDead` — accurate but couples the name to one outcome; the function's contract is "return the truthful record", which on a lost race is the *other* writer's terminal record, not a failure it created.

### Hermetic env pinned at the top of `tests/liveness.test.mjs`
- **Question:** How do the new tests stay correct when the suite runs inside a live Claude Code session (which exports `CLAUDE_PLUGIN_DATA` and `CODEX_COMPANION_SESSION_ID`)?
- **Choice:** Module-level setup at the top of the file: set `process.env.CLAUDE_PLUGIN_DATA` to a fresh temp dir, delete `CODEX_COMPANION_SESSION_ID`/`CODEX_COMPANION_TRANSCRIPT_PATH`. In-process resolvers and spawned CLI children (which inherit `process.env`) then agree on the state root, with no session filter interference.
- **Grounding:** node.md stack shard: process-per-file isolation — "set the environment the module reads before the first import in that file"; `resolveStateRoot()` reads the env at call time, so module-level assignment is sufficient. Precedent: `tests/isolation.test.mjs` pins `CLAUDE_PLUGIN_DATA` to a temp dir.
- **Alternative considered:** Copying isolation.test.mjs's save/restore `withPluginEnvironment` wrapper — rejected: that wrapper exists to vary env *per test* within a file; this file wants one fixed env, and restore-on-exit buys nothing in a process that exits after the file.

### No probe unit test in `tests/process.test.mjs`
- **Question:** `tests/process.test.mjs` tests `terminateProcessTree` at module level — should `isProcessAlive` get a sibling unit test?
- **Choice:** No. Both probe branches (alive → untouched, dead → flipped) are covered through the CLI seam with real sleeper pids (liveness tests 1 and 3).
- **Grounding:** The spec's seam lock: "the plan and implementers inherit these and may not invent others" — the agreed seams are the CLI subprocess and on-disk state only.
- **Alternative considered:** A module-level test with injected `killImpl` — rejected: a third seam, and an injection parameter no production caller needs (YAGNI).

### `--wait` test kills the sleeper immediately after spawning the waiter
- **Question:** How does the `--wait` termination test sequence "worker dies mid-wait" without sleeps or wall-clock assertions?
- **Choice:** Spawn the `status --wait --timeout-ms 15000 --poll-interval-ms 100` child, then SIGKILL the sleeper at once; assert the child exits 0 with `job.status === "failed"` and `waitTimedOut === false`. Whether the first or a later poll observes the death, both outcomes prove prompt termination against the generous 15 s budget.
- **Grounding:** Spec test strategy item 5 verbatim ("promptness is asserted through `waitTimedOut === false` … not wall-clock measurement"); the-bar "Root causes" (no sleep to paper over a race).
- **Alternative considered:** Sleeping until the waiter's first poll before killing — rejected: reintroduces timing flakiness for a distinction the assertion cannot see.

### "Record unchanged" asserted as byte equality
- **Question:** How strictly does the live-pid guard test assert "the record is unchanged"?
- **Choice:** Capture the seeded job file's bytes before the status read and assert `fs.readFileSync` equality after, plus `status === "running"` in the payload.
- **Grounding:** the-bar "Tests that can fail": the alive path performs no write at all, so byte equality is exactly the observable contract; any accidental write (even a no-op rewrite stamping `updatedAt`) turns it red.
- **Alternative considered:** Field-by-field spot checks — weaker; a stray `updatedAt` stamp would survive.

### Commit boundaries: one worktree commit per task, patch (+nix) only
- **Question:** What lands in each worktree commit?
- **Choice:** Task 1: `patches/agent-plugins/codex-plugin-cc.patch` + `lib/agent-plugins.nix`. Tasks 2–3: the patch file only. Nothing from `$SCRATCH` is ever committed; `result` (the `just build` symlink) stays untracked.
- **Grounding:** Dispatch brief ("all code changes land as edits to the patch; the upstream checkout is scratch"); writing-plans "frequent commits" with one reviewable deliverable each.
- **Alternative considered:** A single squashed commit at the end — rejected: loses the per-task review gates sdd depends on.

---

### Task 1: Dead-pid→failed flip on single-job status reads

**Files:**
- Modify (scratch): `plugins/codex/scripts/lib/process.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/state.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/tracked-jobs.mjs`
- Modify (scratch): `plugins/codex/scripts/lib/job-control.mjs`
- Create (scratch): `tests/liveness.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)
- Modify (worktree): `lib/agent-plugins.nix` (`patchRevision` 3→4)

**Interfaces:**
- Consumes: existing exports — `withMetadataLock`/`atomicWriteFile`/`readJobFile`/`resolveJobFile`/`nowIso` (state.mjs internals), `appendLogLine` (tracked-jobs.mjs), `enrichJob`/`matchJobReference` (job-control.mjs).
- Produces (later tasks rely on these exact signatures):
  - `isProcessAlive(pid: number): boolean` exported from `lib/process.mjs` — only `ESRCH` returns false.
  - `updateJobRecord(cwd: string, jobId: string, mutate: (current: object|null) => object|null|undefined): object|null` exported from `lib/state.mjs` — runs `mutate` under the per-job metadata lock; a nullish return means "no write, return `current`"; an object return is written atomically with `updatedAt` stamped and returned.
  - `reconcileWorkerLiveness(workspaceRoot: string, job: object): object` exported from `lib/tracked-jobs.mjs` — returns the input record untouched when it is not probe-eligible or its pid is alive; otherwise returns the persisted truthful record (its own flip, or a concurrent writer's).
  - `tests/liveness.test.mjs` module-level fixtures reused by Tasks 2–3: `SCRIPT`, `spawnSleeper(t, cwd)`, `deadPid(t, cwd)`, `seedJob(workspace, record)`, `runningTaskRecord(workspace, id, pid)` (definitions below).

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Scratch checkout workflow* setup block from the plan header verbatim. Verify:

Run: `git -C /tmp/codex-plugin-cc-issue-2-scratch rev-parse HEAD`
Expected: `db52e28f4d9ded852ab3942cea316258ae4ef346`

- [ ] **Step 2: Write the failing tests**

Create `$SCRATCH/tests/liveness.test.mjs`:

```js
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { makeTempDir, run } from "./helpers.mjs";
import { resolveStateDir } from "../plugins/codex/scripts/lib/state.mjs";

// State resolvers read these variables at call time, and spawned CLI children
// inherit process.env, so pinning them here keeps every test in this file
// hermetic even when the suite runs inside a live Claude Code session.
// node --test runs each file in its own process; nothing leaks across files.
process.env.CLAUDE_PLUGIN_DATA = makeTempDir("codex-plugin-liveness-data-");
delete process.env.CODEX_COMPANION_SESSION_ID;
delete process.env.CODEX_COMPANION_TRANSCRIPT_PATH;

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(ROOT, "plugins", "codex", "scripts", "codex-companion.mjs");
const DEAD_WORKER_MESSAGE = (pid) => `Worker process ${pid} exited without recording a result.`;

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

async function deadPid(t, cwd) {
  const sleeper = spawnSleeper(t, cwd);
  process.kill(sleeper.pid, "SIGKILL");
  await waitFor(() => isPidGone(sleeper.pid));
  return sleeper.pid;
}

function seedJob(workspace, record) {
  const jobsDir = path.join(resolveStateDir(workspace), "jobs");
  fs.mkdirSync(jobsDir, { recursive: true });
  const logFile = path.join(jobsDir, `${record.id}.log`);
  fs.writeFileSync(logFile, `[2026-08-01T10:00:00.000Z] Starting ${record.title}.\n`, "utf8");
  const jobFile = path.join(jobsDir, `${record.id}.json`);
  fs.writeFileSync(jobFile, `${JSON.stringify({ ...record, logFile }, null, 2)}\n`, "utf8");
  return { jobFile, logFile };
}

function runningTaskRecord(workspace, id, pid) {
  return {
    id,
    kind: "task",
    kindLabel: "rescue",
    title: "Codex Task",
    workspaceRoot: workspace,
    jobClass: "task",
    summary: "Investigate flaky test",
    write: false,
    createdAt: "2026-08-01T10:00:00.000Z",
    status: "running",
    startedAt: "2026-08-01T10:00:01.000Z",
    phase: "starting",
    pid,
    updatedAt: "2026-08-01T10:00:02.000Z"
  };
}

test("a running job whose worker pid is dead is flipped to failed by one status read", async (t) => {
  const workspace = makeTempDir();
  const pid = await deadPid(t, workspace);
  const { jobFile, logFile } = seedJob(workspace, runningTaskRecord(workspace, "task-dead", pid));

  const result = run("node", [SCRIPT, "status", "task-dead", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.job.status, "failed");
  assert.equal(payload.job.errorMessage, DEAD_WORKER_MESSAGE(pid));

  const stored = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  assert.equal(stored.status, "failed");
  assert.equal(stored.phase, "failed");
  assert.equal(stored.pid, null);
  assert.ok(stored.completedAt);
  assert.ok(fs.readFileSync(logFile, "utf8").includes(DEAD_WORKER_MESSAGE(pid)));
});

test("a queued job whose worker died before its first write is flipped to failed", async (t) => {
  const workspace = makeTempDir();
  const pid = await deadPid(t, workspace);
  const { jobFile } = seedJob(workspace, {
    id: "task-queued-dead",
    kind: "task",
    kindLabel: "rescue",
    title: "Codex Task",
    workspaceRoot: workspace,
    jobClass: "task",
    summary: "Investigate flaky test",
    write: false,
    createdAt: "2026-08-01T10:00:00.000Z",
    status: "queued",
    phase: "queued",
    pid,
    request: { cwd: workspace, prompt: "Investigate flaky test", write: false },
    updatedAt: "2026-08-01T10:00:01.000Z"
  });

  const result = run("node", [SCRIPT, "status", "task-queued-dead", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.job.status, "failed");
  assert.equal(payload.job.errorMessage, DEAD_WORKER_MESSAGE(pid));
  assert.equal(JSON.parse(fs.readFileSync(jobFile, "utf8")).status, "failed");
  assert.equal(JSON.parse(fs.readFileSync(jobFile, "utf8")).pid, null);
});

test("a running job with a live worker pid is left untouched", (t) => {
  const workspace = makeTempDir();
  const sleeper = spawnSleeper(t, workspace);
  const { jobFile } = seedJob(workspace, runningTaskRecord(workspace, "task-alive", sleeper.pid));
  const seededBytes = fs.readFileSync(jobFile, "utf8");

  const result = run("node", [SCRIPT, "status", "task-alive", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.job.status, "running");
  assert.equal(payload.job.errorMessage, undefined);
  assert.equal(fs.readFileSync(jobFile, "utf8"), seededBytes);
});
```

- [ ] **Step 3: Run the tests and watch them fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: FAIL — tests 1 and 2 report `payload.job.status` is `"running"`/`"queued"`, not `"failed"` (verified at base 2026-08-11: a dead-pid running record is reported `running` with no errorMessage and the on-disk record unchanged). Test 3 may already pass — that is the guard, not the feature.

- [ ] **Step 4: Implement the probe in `lib/process.mjs`**

Append to `$SCRATCH/plugins/codex/scripts/lib/process.mjs`:

```js
export function isProcessAlive(pid) {
  // Only ESRCH proves absence. Success or EPERM (a live process we may not
  // signal) or any other error counts as alive: a wrong "alive" degrades to
  // the pre-probe behavior, a wrong "dead" would fabricate a failure.
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== "ESRCH";
  }
}
```

- [ ] **Step 5: Implement the guarded read-modify-write in `lib/state.mjs`**

Add after `upsertJob` in `$SCRATCH/plugins/codex/scripts/lib/state.mjs` (uses the module-private `withMetadataLock`, `atomicWriteFile`, `nowIso`; a lock-acquisition timeout inside `withMetadataLock` throws and propagates — do not catch it):

```js
export function updateJobRecord(cwd, jobId, mutate) {
  const jobFile = resolveJobFile(cwd, jobId);
  return withMetadataLock(`${jobFile}.lock`, () => {
    let current = null;
    if (fs.existsSync(jobFile)) {
      try {
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
```

- [ ] **Step 6: Implement the transition in `lib/tracked-jobs.mjs`**

In `$SCRATCH/plugins/codex/scripts/lib/tracked-jobs.mjs`, extend the state import and add the process import:

```js
import { readJobFile, resolveJobFile, resolveJobLogFile, updateJobRecord, upsertJob, writeJobFile } from "./state.mjs";
import { isProcessAlive } from "./process.mjs";
```

Add at the end of the file:

```js
function isWorkerProbeEligible(job) {
  return (job?.status === "queued" || job?.status === "running") && Number.isFinite(job?.pid);
}

export function reconcileWorkerLiveness(workspaceRoot, job) {
  if (!isWorkerProbeEligible(job) || isProcessAlive(job.pid)) {
    return job;
  }

  const probedPid = job.pid;
  const errorMessage = `Worker process ${probedPid} exited without recording a result.`;
  let flipped = false;
  const reconciled = updateJobRecord(workspaceRoot, job.id, (current) => {
    if (!isWorkerProbeEligible(current) || current.pid !== probedPid) {
      // A concurrent writer (worker completion, cancel, another reader's
      // flip) reached the record first; keep what it wrote.
      return null;
    }
    flipped = true;
    return {
      ...current,
      status: "failed",
      phase: "failed",
      errorMessage,
      pid: null,
      completedAt: nowIso()
    };
  });

  if (flipped) {
    appendLogLine(reconciled.logFile ?? job.logFile ?? null, errorMessage);
  }
  return reconciled ?? job;
}
```

- [ ] **Step 7: Invoke it from `buildSingleJobSnapshot` in `lib/job-control.mjs`**

Extend the tracked-jobs import at the top of `$SCRATCH/plugins/codex/scripts/lib/job-control.mjs`:

```js
import { reconcileWorkerLiveness, SESSION_ID_ENV } from "./tracked-jobs.mjs";
```

In `buildSingleJobSnapshot`, replace the return statement so the selected record is reconciled before enrichment:

```js
  return {
    workspaceRoot,
    job: enrichJob(reconcileWorkerLiveness(workspaceRoot, selected), { maxProgressLines: options.maxProgressLines })
  };
```

- [ ] **Step 8: Verify — new tests pass, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: PASS — 3 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 99 / # pass 95 / # fail 0 / # skipped 4`. In particular `status --wait times out cleanly when a job is still active` (pid-less running record, `tests/runtime.test.mjs`) must still pass — it pins the probe-eligibility boundary this task must not cross.

- [ ] **Step 9: Regenerate the patch and bump `patchRevision`**

Run the *Regeneration* block from the plan header. Then in the worktree edit `lib/agent-plugins.nix`: `patchRevision = 3;` → `patchRevision = 4;`.

Run: `git -C "$WORKTREE" diff --stat -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix`
Expected: both files modified; the patch diff includes the new `tests/liveness.test.mjs` hunks, the four `lib/*.mjs` changes, and the one-line stale index-hash correction (`ab0aa35` → `ce1552b`) described in the plan header.

- [ ] **Step 10: `just build`**

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then `nix-store -qR ./result | grep codex-plugin-cc` lists a path containing `codex-plugin-cc-1.0.6-nix.db52e28f.p4` (the p4 marketplace built from the regenerated patch).

- [ ] **Step 11: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "feat(agent-plugins): flip dead-pid companion jobs to failed on status reads

A codex-companion status read of a queued/running job probes the recorded
worker pid (kill(pid,0), only ESRCH means dead) and persists the failed
transition under the per-job metadata lock, naming the dead worker in the
record and the job log. Patch p4 against codex-plugin-cc db52e28f.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Listing reconciliation and prompt `--wait` termination

**Files:**
- Modify (scratch): `plugins/codex/scripts/lib/job-control.mjs`
- Modify (scratch): `tests/liveness.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)

**Interfaces:**
- Consumes: `reconcileWorkerLiveness(workspaceRoot, job)` from `lib/tracked-jobs.mjs` (Task 1; already imported in job-control.mjs) — returns the input record untouched when not probe-eligible or alive, else the persisted truthful record. Test fixtures from Task 1's `tests/liveness.test.mjs`: `SCRIPT`, `spawnSleeper(t, cwd)`, `deadPid(t, cwd)`, `seedJob(workspace, record)`, `runningTaskRecord(workspace, id, pid)`.
- Produces: no new exports; `buildStatusSnapshot` reconciles the session-filtered records it surfaces. `status <id> --wait` requires no code change — it polls `buildSingleJobSnapshot`, whose Task 1 reconciliation ends the poll loop; this task proves that with a test.

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Scratch checkout workflow* setup block from the plan header verbatim (it applies the Task 1 patch, so all Task 1 code and tests are present). Verify:

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: PASS — 3 tests, 0 fail.

- [ ] **Step 2: Write the failing tests**

Append to `$SCRATCH/tests/liveness.test.mjs`:

```js
test("the status listing surfaces a dead-worker job as the failed latest-finished job", async (t) => {
  const workspace = makeTempDir();
  const pid = await deadPid(t, workspace);
  seedJob(workspace, runningTaskRecord(workspace, "task-listed-dead", pid));

  const result = run("node", [SCRIPT, "status", "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.running.length, 0);
  assert.equal(payload.latestFinished?.id, "task-listed-dead");
  assert.equal(payload.latestFinished?.status, "failed");
  assert.equal(payload.latestFinished?.errorMessage, DEAD_WORKER_MESSAGE(pid));
});

test("status --wait returns the failed state promptly when the worker dies mid-wait", async (t) => {
  const workspace = makeTempDir();
  const sleeper = spawnSleeper(t, workspace);
  seedJob(workspace, runningTaskRecord(workspace, "task-wait-dead", sleeper.pid));

  const child = spawn(
    "node",
    [SCRIPT, "status", "task-wait-dead", "--wait", "--timeout-ms", "15000", "--poll-interval-ms", "100", "--json"],
    { cwd: workspace, stdio: ["ignore", "pipe", "pipe"] }
  );
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  const exited = new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (status) => resolve(status));
  });

  process.kill(sleeper.pid, "SIGKILL");

  const status = await exited;
  assert.equal(status, 0, stderr);
  const payload = JSON.parse(stdout);
  assert.equal(payload.job.status, "failed");
  assert.equal(payload.waitTimedOut, false);
});
```

- [ ] **Step 3: Run the tests and watch the listing test fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: the listing test FAILS — `payload.running` still contains `task-listed-dead` (the listing path has no probe yet; only single-job reads reconcile after Task 1). The `--wait` test already passes on Task 1's wiring (each poll runs `buildSingleJobSnapshot`) — it is committed by this task as the regression pin for AC2.

- [ ] **Step 4: Reconcile surfaced records in `buildStatusSnapshot`**

In `$SCRATCH/plugins/codex/scripts/lib/job-control.mjs`, `buildStatusSnapshot`, replace the `jobs` assignment:

```js
  const jobs = sortJobsNewestFirst(
    filterJobsForCurrentSession(listJobs(workspaceRoot), options).map((job) =>
      reconcileWorkerLiveness(workspaceRoot, job)
    )
  );
```

Reconcile-then-sort is deliberate: the flip stamps a fresh `updatedAt`, so sorting afterwards is what makes the flipped job the newest finished record (`latestFinished`) in the same read. The map runs after the session filter, so the listing only ever rewrites records it surfaces; jobs of other sessions are healed by their own session's listing or any single-job read.

- [ ] **Step 5: Verify — new tests pass, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: PASS — 5 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 101 / # pass 97 / # fail 0 / # skipped 4`. `status without a job id only shows jobs from the current Claude session` (`tests/runtime.test.mjs`) must still pass — it pins the session filter the reconciliation must stay behind.

- [ ] **Step 6: Regenerate the patch, `just build`**

Run the *Regeneration* block from the plan header (patchRevision stays 4).

Run (from `$WORKTREE`): `just build`
Expected: exits 0; `nix-store -qR ./result | grep codex-plugin-cc` still lists the `.p4` path.

- [ ] **Step 7: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "feat(agent-plugins): reconcile status listing and end status --wait on dead workers

The status listing probes the active records it surfaces (after the session
filter) so a dead-worker job leaves the running section and becomes the
failed latest-finished job in the same read; status --wait ends on the next
poll after the flip instead of sleeping until its timeout.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Reviewer runtime cleanup on the dead-worker flip

**Files:**
- Modify (scratch): `plugins/codex/scripts/lib/tracked-jobs.mjs`
- Modify (scratch): `tests/liveness.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)

**Interfaces:**
- Consumes: `reconcileWorkerLiveness` (Task 1, in `lib/tracked-jobs.mjs`) and its `updateJobRecord` callback; `cleanupReviewerRuntime(cwd, jobId)` / `resolveReviewerRuntimeHome(cwd, jobId)` from `lib/runtime-home.mjs` (exist at base; cleanup is idempotent and path-guarded). Test fixtures from Task 1: `SCRIPT`, `deadPid(t, cwd)`, `seedJob(workspace, record)`; this task adds the `resolveReviewerRuntimeHome` import to `tests/liveness.test.mjs`.
- Produces: the invariant "terminal record ⇒ no reviewer runtime directory" holds on the dead-worker path (it already holds for success/failure/timeout via `withAppServer`'s `finally` and for cancel via `handleCancel` — both unchanged).

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Scratch checkout workflow* setup block from the plan header verbatim. Verify:

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: PASS — 5 tests, 0 fail.

- [ ] **Step 2: Write the failing test**

Add to the imports at the top of `$SCRATCH/tests/liveness.test.mjs` (below the `state.mjs` import):

```js
import { resolveReviewerRuntimeHome } from "../plugins/codex/scripts/lib/runtime-home.mjs";
```

Append to the end of the file:

```js
test("the dead-worker flip removes the reviewer runtime directory", async (t) => {
  const workspace = makeTempDir();
  const pid = await deadPid(t, workspace);
  const jobId = "reviewer-dead";
  const { jobFile } = seedJob(workspace, {
    id: jobId,
    kind: "plan-review",
    kindLabel: "review",
    title: "Isolated Plan Review",
    workspaceRoot: workspace,
    jobClass: "review",
    summary: "Review the proposed plan",
    write: false,
    createdAt: "2026-08-01T10:00:00.000Z",
    status: "running",
    startedAt: "2026-08-01T10:00:01.000Z",
    phase: "starting",
    pid,
    updatedAt: "2026-08-01T10:00:02.000Z"
  });
  const runtimeHome = resolveReviewerRuntimeHome(workspace, jobId);
  fs.mkdirSync(runtimeHome, { recursive: true });
  fs.writeFileSync(path.join(runtimeHome, "config.toml"), 'model = "reviewer"\n', "utf8");

  const result = run("node", [SCRIPT, "status", jobId, "--json"], { cwd: workspace });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).job.status, "failed");
  assert.equal(JSON.parse(fs.readFileSync(jobFile, "utf8")).status, "failed");
  assert.equal(fs.existsSync(runtimeHome), false);
});
```

- [ ] **Step 3: Run the test and watch it fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: FAIL — the record flips to `failed` (Task 1 behavior) but `fs.existsSync(runtimeHome)` is still `true`: nothing on the flip path removes the directory yet.

- [ ] **Step 4: Clean the reviewer runtime inside the locked callback**

In `$SCRATCH/plugins/codex/scripts/lib/tracked-jobs.mjs`, add the import:

```js
import { cleanupReviewerRuntime } from "./runtime-home.mjs";
```

In `reconcileWorkerLiveness`, inside the `updateJobRecord` callback, insert between the re-check and `flipped = true;`:

```js
    if (current.kind === "plan-review") {
      // Cleanup precedes the terminal write: if this process dies between the
      // two, the record is still active and the next status read retries both.
      // The reverse order would leave a terminal record with a permanent leak
      // no reader would ever revisit. cleanupReviewerRuntime is idempotent, so
      // a racing double-cleanup is harmless.
      cleanupReviewerRuntime(workspaceRoot, current.id);
    }
```

- [ ] **Step 5: Verify — new test passes, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/liveness.test.mjs`
Expected: PASS — 6 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 102 / # pass 98 / # fail 0 / # skipped 4`. The pre-existing cleanup pins must still pass: `reviewer tasks run foreground in a fresh read-only runtime and clean it up` (`tests/runtime.test.mjs`) and `workspace and reviewer runtimes isolate every mutable Codex path` (`tests/isolation.test.mjs`).

- [ ] **Step 6: Final verification — regenerate, revision check, `just build`**

Run the *Regeneration* block from the plan header.

Run: `grep -n 'patchRevision = ' "$WORKTREE/lib/agent-plugins.nix"`
Expected: `patchRevision = 4;` (bumped in Task 1; this task must not change it).

Determinism check — a pristine re-apply of the committed patch reproduces itself:

```bash
git -C "$SCRATCH" reset --hard && git -C "$SCRATCH" checkout --force --detach "$PIN" && git -C "$SCRATCH" clean -ffd
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" | diff - "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```
Expected: `diff` prints nothing (exit 0).

Run (from `$WORKTREE`): `just build`
Expected: exits 0; `nix-store -qR ./result | grep codex-plugin-cc` lists a `codex-plugin-cc-1.0.6-nix.db52e28f.p4` path, and inside it `tests/liveness.test.mjs` exists and `plugins/codex/scripts/lib/tracked-jobs.mjs` contains `reconcileWorkerLiveness` — proof the patch applies under nix's `patch -p1` and ships the feature.

Optional corroboration (non-gating, mirrors the issue demo): seed a dead-pid `plan-review` record plus a runtime directory in a temp workspace, run `node "$SCRATCH/plugins/codex/scripts/codex-companion.mjs" status <jobId>` (no `--json`), and observe the human report's log preview naming the dead worker while the runtime directory is gone.

- [ ] **Step 7: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "feat(agent-plugins): remove reviewer runtime when the dead-worker flip fires

The status reader that persists the dead-pid failed transition removes the
job's reviewer-runtimes directory inside the same lock scope, before the
terminal write, so every terminal path leaves no runtime directory behind.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Spec coverage

- R1/AC1 (dead pid → failed with error naming the worker, persisted, single read and listing): Task 1 (single read, queued and running, live-pid guard), Task 2 (listing).
- R2/AC2 (`--wait` returns promptly): Task 2 (wait test; mechanism delivered by Task 1's snapshot reconciliation).
- R3/AC3 (no reviewer runtime after any terminal state): Task 3 (dead-worker path; success/timeout and cancel paths unchanged and pinned by existing tests).
- R4/AC4 (full suite green incl. new behavior tests, no call-count assertions): every task's suite gate; final count 102/98/0/4.
- R5/AC5 (patch regenerated, patchRevision 3→4, `just build` green): Task 1 (bump + build), every task (regen + build), Task 3 Step 6 (final determinism + closure check).
