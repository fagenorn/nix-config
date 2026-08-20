# Task 1: Preserve Detached Review Operation Identity and Shared Lifecycle

**Files:**
- Modify: `patches/agent-plugins/codex-plugin-cc.patch`
- Modify: `lib/agent-plugins.nix`
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Scratch source captured by the regenerated patch: `plugins/codex/agents/codex-reviewer.md`
- Scratch source captured by the regenerated patch: `plugins/codex/scripts/codex-companion.mjs`
- Scratch source captured by the regenerated patch: `plugins/codex/scripts/lib/render.mjs`
- Scratch source captured by the regenerated patch: `plugins/codex/scripts/lib/tracked-jobs.mjs`
- Scratch source captured by the regenerated patch: `plugins/codex/scripts/session-lifecycle-hook.mjs`
- Scratch tests captured by the regenerated patch: `tests/commands.test.mjs`
- Scratch tests captured by the regenerated patch: `tests/render.test.mjs`
- Scratch tests captured by the regenerated patch: `tests/reviewer-detach.test.mjs`
- Scratch tests captured by the regenerated patch: `tests/liveness.test.mjs`
- Scratch tests captured by the regenerated patch: `tests/runtime.test.mjs`
- Scratch tests captured by the regenerated patch: `tests/worker-postmortem.test.mjs`

**Interfaces:**
- Consumes: the collaboration dispatch's exact two-line envelope and the existing `task`, `task-worker`, `status`, `result`, and `cancel` commands; `createReviewerRuntime`/`cleanupReviewerRuntime`; durable job files with `kind`, `kindLabel`, `jobClass`, `request`, and status fields.
- Produces: value-bearing CLI `task --reviewer <plan-review|diff-review>`; persisted `request.reviewOperation: "plan-review" | "diff-review"`; records and JSON payloads whose `kind`/`kindLabel` equal that value; operation-specific title; common `jobClass: "review"`; human result headed by the operation-specific title with unchanged raw output beneath it.
- Produces: bridge contract requiring exactly one `REVIEW_OPERATION:` line immediately after `WORKTREE_ROOT:` and forwarding it to `--reviewer`; the bridge continues to return `storedJob.result.rawOutput` unchanged.

**Invariants:**
- The only accepted review-operation values are `plan-review` and `diff-review`; missing, duplicated, ambiguous, or unsupported declarations fail before launch, and a crafted invalid stored request fails before reviewer execution (D1).
- `reviewOperation !== null` alone selects fresh/read-only/no-persistence/840000 ms reviewer execution; the operation value does not change runtime policy (D1).
- Launch JSON, durable request/job, status JSON/human label, result JSON/human heading, title, and cancellation payload never collapse `diff-review` to `plan-review` or generic `review` (D1).
- Raw reviewer output is byte-identical in `storedJob.result.rawOutput` and starts immediately below the human operation header; the collaboration bridge extracts the raw field, not the human rendering (D1).
- Once a valid record exists, cancellation, dead-worker cleanup, SessionEnd cleanup/terminalization, and retention use `jobClass === "review"` plus existing status predicates; a legacy `plan-review` record with `jobClass: "review"` remains supported without migration (D2).
- Both operation kinds receive distinct per-job runtime homes, read-only sandboxing, cleanup-before-terminal-write, no thread persistence, and the same timeout (D2).
- The repository patch is a deterministic zero-context diff from the pinned upstream revision and `patchRevision` becomes `10`.

- [ ] **Step 1: Create the pinned scratch checkout and write the failing operation-contract tests**

From the worktree root, create one scratch checkout and keep both paths in task-specific variables for every later command:

```bash
WORKTREE_ROOT="$PWD"
PLUGIN_PIN=db52e28f4d9ded852ab3942cea316258ae4ef346
PLUGIN_SCRATCH=$(mktemp -d)
gh repo clone openai/codex-plugin-cc "$PLUGIN_SCRATCH"
git -C "$PLUGIN_SCRATCH" checkout "$PLUGIN_PIN"
git -C "$PLUGIN_SCRATCH" apply --unidiff-zero "$WORKTREE_ROOT/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$PLUGIN_SCRATCH" add -N .
```

In scratch `tests/reviewer-detach.test.mjs`, replace the single-operation background success case with this shared contract (retain the file's existing imports/helpers):

```js
for (const operation of ["plan-review", "diff-review"]) {
  test(`a background ${operation} survives its launcher and preserves operation identity`, async () => {
    const repo = makeReviewRepo();
    const binDir = makeTempDir();
    const canonicalHome = makeCanonicalHome();
    installFakeCodex(binDir, "slow-task");
    const env = { ...buildEnv(binDir), CODEX_HOME: canonicalHome };
    const title = operation === "plan-review" ? "Codex Plan Review" : "Codex Diff Review";

    const launched = run(
      "node",
      [SCRIPT, "task", "--fresh", "--reviewer", operation, "--background", "--json"],
      { cwd: repo, env, input: "review packet" }
    );
    assert.equal(launched.status, 0, launched.stderr);
    const launch = JSON.parse(launched.stdout);
    assert.equal(launch.status, "queued");
    assert.equal(launch.kind, operation);
    assert.equal(launch.title, title);
    assert.match(launch.jobId, /^reviewer-/);

    const waited = run(
      "node",
      [SCRIPT, "status", launch.jobId, "--wait", "--timeout-ms", "15000", "--json"],
      { cwd: repo, env }
    );
    assert.equal(waited.status, 0, waited.stderr);
    const statusJob = JSON.parse(waited.stdout).job;
    assert.equal(statusJob.status, "completed");
    assert.equal(statusJob.kind, operation);
    assert.equal(statusJob.kindLabel, operation);
    assert.equal(statusJob.jobClass, "review");
    assert.equal(statusJob.title, title);

    const collected = run("node", [SCRIPT, "result", launch.jobId, "--json"], { cwd: repo, env });
    assert.equal(collected.status, 0, collected.stderr);
    const result = JSON.parse(collected.stdout);
    assert.equal(result.job.kind, operation);
    assert.equal(result.storedJob.kind, operation);
    assert.equal(result.storedJob.request.reviewOperation, operation);
    assert.equal(result.storedJob.result.rawOutput, "Handled the requested task.\nTask prompt accepted.");

    const human = run("node", [SCRIPT, "result", launch.jobId], { cwd: repo, env });
    assert.equal(human.status, 0, human.stderr);
    assert.ok(human.stdout.startsWith(`# ${title}\n\nHandled the requested task.\nTask prompt accepted.`), human.stdout);

    const fakeState = JSON.parse(fs.readFileSync(path.join(binDir, "fake-codex-state.json"), "utf8"));
    assert.equal(fakeState.lastThreadStart.sandbox, "read-only");
    assert.equal(fakeState.lastCodexHome, resolveReviewerRuntimeHome(repo, launch.jobId));
    assert.equal(fs.existsSync(fakeState.lastCodexHome), false);
    assert.equal(fs.readFileSync(path.join(canonicalHome, "config.toml"), "utf8"), 'model = "canonical"\n');
  });
}
```

Add these CLI validation cases in the same file:

```js
test("reviewer operation is required and closed before launch", () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  installFakeCodex(binDir);

  for (const args of [
    [SCRIPT, "task", "--fresh", "--reviewer", "--background", "--json"],
    [SCRIPT, "task", "--fresh", "--reviewer", "security-review", "--background", "--json"]
  ]) {
    const result = run("node", args, { cwd: repo, env: buildEnv(binDir), input: "review packet" });
    assert.notEqual(result.status, 0, result.stdout);
    assert.match(result.stderr, /--reviewer must be plan-review or diff-review\./);
  }
});
```

Import `readJobFile`, `resolveJobFile`, and `writeJobFile` from `../plugins/codex/scripts/lib/state.mjs`, then add the worker-boundary case:

```js
test("task-worker rejects a crafted persisted review operation before execution", () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const jobId = "reviewer-invalid-operation";
  const now = new Date().toISOString();
  writeJobFile(repo, jobId, {
    id: jobId,
    kind: "diff-review",
    kindLabel: "diff-review",
    title: "Codex Diff Review",
    workspaceRoot: repo,
    jobClass: "review",
    summary: "Review packet",
    write: false,
    status: "queued",
    phase: "queued",
    createdAt: now,
    updatedAt: now,
    request: {
      cwd: repo,
      model: null,
      effort: null,
      prompt: "review packet",
      write: false,
      resumeLast: false,
      reviewOperation: "security-review",
      timeoutMs: 5000,
      jobId
    }
  });

  const worker = run("node", [SCRIPT, "task-worker", "--cwd", repo, "--job-id", jobId], {
    cwd: repo,
    env: buildEnv(binDir)
  });
  assert.equal(worker.status, 0, worker.stderr);
  const stored = readJobFile(resolveJobFile(repo, jobId));
  assert.equal(stored.status, "failed");
  assert.match(stored.errorMessage, /Stored review operation must be plan-review or diff-review\./);
});
```

In scratch `tests/render.test.mjs`, add the exact human/raw rendering contract:

```js
test("transport review results identify the operation above unchanged raw output", () => {
  for (const [kind, title] of [
    ["plan-review", "Codex Plan Review"],
    ["diff-review", "Codex Diff Review"]
  ]) {
    const rawOutput = "line one\nline two\n";
    const output = renderStoredJobResult(
      { id: `reviewer-${kind}`, kind, kindLabel: kind, status: "completed", title, jobClass: "review" },
      { kind, jobClass: "review", result: { rawOutput } }
    );
    assert.equal(output, `# ${title}\n\n${rawOutput}`);
  }
});
```

In scratch `tests/commands.test.mjs`, replace the bridge launch assertion with the complete envelope contract:

```js
test("the reviewer bridge validates and forwards one explicit operation envelope", () => {
  const agent = read("agents/codex-reviewer.md");
  assert.match(agent, /first two lines are exactly `WORKTREE_ROOT: <absolute path>` and `REVIEW_OPERATION: <operation>`/);
  assert.match(agent, /exactly one `REVIEW_OPERATION:` declaration/);
  assert.match(agent, /only accepted values are `plan-review` and `diff-review`/);
  assert.match(agent, /task --fresh --reviewer <operation> --background --json/);
  assert.match(agent, /--wait --timeout-ms 540000/);
  assert.match(agent, /storedJob\?\.result\?\.rawOutput/);
  assert.match(agent, /CODEX_REVIEW_FAILURE:/);
  assert.match(agent, /Never pass `run_in_background`/);
  assert.doesNotMatch(agent, /run_in_background:\s*true/);
  assert.doesNotMatch(agent, /completion notification/i);
});
```

In repository `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add:

```python
    def test_codex_collaboration_dispatch_carries_operation_envelope(self):
        launch = self.section(
            self.collaboration,
            "Build the operation's packet",
            "Parallel reviews are valid.",
        )
        self.assertIn("first two lines", launch)
        self.assertIn("`WORKTREE_ROOT: <absolute worktree root>`", launch)
        self.assertIn("`REVIEW_OPERATION: <plan-review|diff-review>`", launch)
        self.assert_ordered(launch, "WORKTREE_ROOT:", "REVIEW_OPERATION:", "Launch mechanics")
```

Update every pre-existing reviewer record fixture in `tests/liveness.test.mjs` and `tests/worker-postmortem.test.mjs` to the production shape `jobClass: "review"`; in particular, the already-terminal and divergent-state-dir fixtures currently inherit `jobClass: "task"` from `activeRecord`, which would test an impossible record after D2. Keep their existing cleanup-before-terminal-write, terminal retention, divergent state-dir, and active-record-retention assertions unchanged. Replace the single foreground isolation case in `tests/runtime.test.mjs` with the shared case below; cancellation coverage lives in `tests/reviewer-detach.test.mjs` below.

Use these complete cases rather than duplicating lifecycle implementation per operation. In `tests/liveness.test.mjs`, replace the existing reviewer-runtime case with:

```js
for (const operation of ["plan-review", "diff-review"]) {
  test(`a dead ${operation} worker is failed without losing kind and its runtime is removed`, async (t) => {
    const workspace = makeTempDir();
    const pid = await deadPid(t, workspace);
    const jobId = `reviewer-dead-${operation}`;
    const { jobFile } = seedJob(workspace, {
      id: jobId,
      kind: operation,
      kindLabel: operation,
      title: operation === "plan-review" ? "Codex Plan Review" : "Codex Diff Review",
      workspaceRoot: workspace,
      jobClass: "review",
      summary: "Review packet",
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
    const visible = JSON.parse(result.stdout).job;
    const stored = JSON.parse(fs.readFileSync(jobFile, "utf8"));
    assert.equal(visible.status, "failed");
    assert.equal(visible.kind, operation);
    assert.equal(stored.status, "failed");
    assert.equal(stored.kind, operation);
    assert.equal(fs.existsSync(runtimeHome), false);
  });
}
```

In `tests/worker-postmortem.test.mjs`, add:

```js
for (const operation of ["plan-review", "diff-review"]) {
  test(`SessionEnd shares live and terminal cleanup for ${operation}`, async (t) => {
    const workspace = makeTempDir();
    const sessionId = `sess-${operation}`;
    const liveId = `reviewer-live-${operation}`;
    const sleeper = spawnSleeper(t, workspace);
    const liveRuntime = resolveReviewerRuntimeHome(workspace, liveId);
    fs.mkdirSync(liveRuntime, { recursive: true });
    const { jobFile: liveJobFile } = seedJob(
      workspace,
      activeRecord(workspace, liveId, sleeper.pid, sessionId, {
        kind: operation,
        kindLabel: operation,
        title: operation === "plan-review" ? "Codex Plan Review" : "Codex Diff Review",
        jobClass: "review"
      })
    );

    const liveResult = runSessionEndHook(workspace, sessionId);
    assert.equal(liveResult.status, 0, liveResult.stderr);
    await waitFor(() => isPidGone(sleeper.pid));
    const liveStored = JSON.parse(fs.readFileSync(liveJobFile, "utf8"));
    assert.equal(liveStored.status, "cancelled");
    assert.equal(liveStored.kind, operation);
    assert.equal(fs.existsSync(liveRuntime), false);

    const terminalId = `reviewer-terminal-${operation}`;
    const terminalRuntime = resolveReviewerRuntimeHome(workspace, terminalId);
    fs.mkdirSync(terminalRuntime, { recursive: true });
    const { jobFile: terminalJobFile } = seedJob(
      workspace,
      activeRecord(workspace, terminalId, null, sessionId, {
        kind: operation,
        kindLabel: operation,
        title: operation === "plan-review" ? "Codex Plan Review" : "Codex Diff Review",
        jobClass: "review",
        status: "failed",
        phase: "failed",
        pid: null,
        completedAt: "2026-08-01T10:00:09.000Z",
        errorMessage: DEAD_WORKER_MESSAGE(4242)
      })
    );

    const terminalResult = runSessionEndHook(workspace, sessionId);
    assert.equal(terminalResult.status, 0, terminalResult.stderr);
    const terminalStored = JSON.parse(fs.readFileSync(terminalJobFile, "utf8"));
    assert.equal(terminalStored.status, "failed");
    assert.equal(terminalStored.kind, operation);
    assert.equal(fs.existsSync(terminalRuntime), false);
  });
}
```

In `tests/reviewer-detach.test.mjs`, add this observable cancellation case:

```js
for (const operation of ["plan-review", "diff-review"]) {
  test(`cancelling ${operation} uses isolated review cleanup`, async () => {
    const repo = makeReviewRepo();
    const binDir = makeTempDir();
    installFakeCodex(binDir, "interruptible-slow-task");
    const env = buildEnv(binDir);
    const launched = run(
      "node",
      [SCRIPT, "task", "--fresh", "--reviewer", operation, "--background", "--json"],
      { cwd: repo, env, input: "review packet" }
    );
    assert.equal(launched.status, 0, launched.stderr);
    const jobId = JSON.parse(launched.stdout).jobId;

    const cancelled = run("node", [SCRIPT, "cancel", jobId, "--json"], { cwd: repo, env });
    assert.equal(cancelled.status, 0, cancelled.stderr);
    const cancelPayload = JSON.parse(cancelled.stdout);
    assert.equal(cancelPayload.status, "cancelled");
    assert.equal(cancelPayload.turnInterruptAttempted, false);

    const collected = run("node", [SCRIPT, "result", jobId, "--json"], { cwd: repo, env });
    assert.equal(collected.status, 0, collected.stderr);
    const stored = JSON.parse(collected.stdout).storedJob;
    assert.equal(stored.status, "cancelled");
    assert.equal(stored.kind, operation);
    assert.equal(fs.existsSync(resolveReviewerRuntimeHome(repo, jobId)), false);
  });
}
```

In `tests/runtime.test.mjs`, replace the single foreground reviewer test with:

```js
for (const operation of ["plan-review", "diff-review"]) {
  test(`foreground ${operation} uses fresh read-only isolation`, () => {
    const repo = makeTempDir();
    const binDir = makeTempDir();
    const canonicalHome = makeTempDir();
    const statePath = path.join(binDir, "fake-codex-state.json");
    installFakeCodex(binDir);
    initGitRepo(repo);
    fs.writeFileSync(path.join(repo, "README.md"), "hello\n");
    run("git", ["add", "README.md"], { cwd: repo });
    run("git", ["commit", "-m", "init"], { cwd: repo });
    fs.writeFileSync(path.join(canonicalHome, "auth.json"), "{}\n");
    fs.writeFileSync(path.join(canonicalHome, "config.toml"), 'model = "canonical"\n');

    const result = run(
      "node",
      [SCRIPT, "task", "--fresh", "--reviewer", operation, "--timeout-ms", "5000", "--json", "review packet"],
      { cwd: repo, env: { ...buildEnv(binDir), CODEX_HOME: canonicalHome } }
    );

    assert.equal(result.status, 0, result.stderr);
    const [job] = listJobs(repo);
    assert.equal(job.kind, operation);
    assert.equal(job.kindLabel, operation);
    assert.equal(job.jobClass, "review");
    assert.equal(job.status, "completed");
    const fakeState = JSON.parse(fs.readFileSync(statePath, "utf8"));
    assert.equal(fakeState.lastThreadStart.approvalPolicy, "never");
    assert.equal(fakeState.lastThreadStart.sandbox, "read-only");
    assert.equal(fakeState.lastThreadStart.ephemeral, true);
    assert.equal(fakeState.lastCodexHome, resolveReviewerRuntimeHome(repo, job.id));
    assert.notEqual(fakeState.lastCodexHome, canonicalHome);
    assert.equal(fs.existsSync(fakeState.lastCodexHome), false);
  });
}
```

- [ ] **Step 2: Run the focused tests and observe the base failures**

Run in the patched scratch checkout:

```bash
env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
  node --test tests/commands.test.mjs tests/render.test.mjs tests/reviewer-detach.test.mjs \
  tests/liveness.test.mjs tests/runtime.test.mjs tests/worker-postmortem.test.mjs
```

Expected at starting commit `e15909b`: FAIL for one reason across the new cases — `--reviewer` is boolean, the CLI always persists `kind: "plan-review"`, its request stores `reviewer: true`, human raw results have no operation header, and the lifecycle still has literal `kind === "plan-review"` branches. The existing plan-review behavior remains green.

Run in the repository worktree:

```bash
python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.WorkflowSkillContractsTest.test_codex_collaboration_dispatch_carries_operation_envelope
```

Expected at `e15909b`: FAIL — `SKILL.md` dispatches only `WORKTREE_ROOT:` and does not require the `REVIEW_OPERATION:` second line.

- [ ] **Step 3: Implement the closed operation ingress and operation-specific surfaces**

In scratch `plugins/codex/scripts/codex-companion.mjs`:

- Define one authoritative `REVIEW_OPERATIONS = new Set(["plan-review", "diff-review"])` and a validator that returns the value or throws the exact CLI/worker diagnostics pinned above. Do not silently default.
- Move `reviewer` from `booleanOptions` to `valueOptions`. Normalize `options.reviewer` before constructing metadata, requests, or jobs. Keep `--reviewer` incompatible with `--write` and resume modes.
- Rename internal boolean plumbing to `reviewOperation`; derive a local `isReviewer = reviewOperation !== null` only for shared runtime policy. `buildTaskRequest` emits `reviewOperation`, never a redundant boolean. `executeTaskRun` revalidates a stored non-null operation before `ensureCodexAvailable` or runtime construction.
- `buildTaskRunMetadata` returns `Codex Plan Review` or `Codex Diff Review`; `buildTaskJob` persists `kind` and `kindLabel` equal to the operation and `jobClass: "review"`; launch payload includes `kind`.
- Read-only sandbox, no thread persistence/name, `reviewerJobId`, touched-file refusal, and the 840000 ms default all derive from `isReviewer` and are otherwise unchanged.
- Keep non-review `task` behavior byte-compatible. Do not change native `review` or `adversarial-review` commands.

In scratch `plugins/codex/scripts/lib/render.mjs`, special-case only transport reviews whose `jobClass === "review"` and `kind` is in the closed operation set: return `# ${job.title}\n\n` followed by the stored raw output, preserving its bytes/newline. Keep structured native review rendering and task rendering unchanged.

In scratch `plugins/codex/agents/codex-reviewer.md`, describe live behavior: the first two dispatch lines are exact; extract and validate exactly one declaration against the closed set; remove both envelope lines from the unchanged packet; launch `task --fresh --reviewer <operation> --background --json`; keep bounded waits and raw JSON extraction unchanged. Fail before launch with one `CODEX_REVIEW_FAILURE:` line when the root/operation envelope is missing, duplicated, ambiguous, invalid, or the root is not absolute.

In repository `home/common/claude-code/skills/codex-collaboration/SKILL.md`, require the caller to dispatch both exact lines in order and state that `<operation>` is the operation currently being invoked. Do not change packet bodies, fallback policy, reviewer runtime policy, or validation/disposition.

- [ ] **Step 4: Collapse lifecycle behavior onto the review class**

In scratch sources, replace only post-ingress literal plan-review predicates:

- `codex-companion.mjs` cancellation skips broker interruption and cleans the isolated runtime when `job.jobClass === "review"`.
- `lib/tracked-jobs.mjs` dead-worker reconciliation cleans before terminal persistence when `current.jobClass === "review"`.
- `session-lifecycle-hook.mjs` live terminalization and already-terminal retry cleanup use `job.jobClass === "review"` / `current.jobClass === "review"`.
- Status continues to derive phase from `jobClass`; new transport records already carry operation-specific `kindLabel`. Do not introduce a plan/diff switch in any lifecycle function.
- Retention remains status-based and retains active records regardless of operation. Legacy `kind: "plan-review", jobClass: "review"` records therefore traverse the same paths without migration.

Run a bounded source inspection in the scratch tree:

```bash
rg -n 'kind === "plan-review"|kind === "diff-review"' \
  plugins/codex/scripts/codex-companion.mjs \
  plugins/codex/scripts/lib/tracked-jobs.mjs \
  plugins/codex/scripts/session-lifecycle-hook.mjs
```

Expected: no lifecycle match. Closed-set ingress/display checks may mention operation literals only in their authoritative validator/title mapping and renderer.

- [ ] **Step 5: Verify the patched source, regenerate the repository patch, and bump its revision**

Run focused and full plugin suites from the scratch checkout:

```bash
env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
  node --test tests/commands.test.mjs tests/render.test.mjs tests/reviewer-detach.test.mjs \
  tests/liveness.test.mjs tests/runtime.test.mjs tests/worker-postmortem.test.mjs
env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
  node --test tests/*.test.mjs
```

Expected: both commands PASS; shared cases prove both operations and no test-created broker/runtime remains.

Regenerate exactly from the pin, then update the repository revision:

```bash
git -C "$PLUGIN_SCRATCH" add -N .
git -C "$PLUGIN_SCRATCH" diff -U0 "$PLUGIN_PIN" > "$WORKTREE_ROOT/patches/agent-plugins/codex-plugin-cc.patch"
```

Edit `lib/agent-plugins.nix` so `patchRevision = 10;`. Then prove the checked-in patch reproduces the scratch source without inspecting patch text:

```bash
PATCH_CHECK=$(mktemp -d)
gh repo clone openai/codex-plugin-cc "$PATCH_CHECK"
git -C "$PATCH_CHECK" checkout "$PLUGIN_PIN"
git -C "$PATCH_CHECK" apply --unidiff-zero "$WORKTREE_ROOT/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$PATCH_CHECK" add -N .
git -C "$PATCH_CHECK" diff -U0 "$PLUGIN_PIN" | diff - "$WORKTREE_ROOT/patches/agent-plugins/codex-plugin-cc.patch"
```

Expected: `diff` exits 0 with no output. A non-zero exit or any output means regeneration is incomplete.

- [ ] **Step 6: Verify repository integration**

Run:

```bash
python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.WorkflowSkillContractsTest.test_codex_collaboration_dispatch_carries_operation_envelope
just build
git diff --check -- \
  patches/agent-plugins/codex-plugin-cc.patch \
  lib/agent-plugins.nix \
  home/common/claude-code/skills/codex-collaboration/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

Expected: the focused workflow test and Nix build PASS; `git diff --check` exits 0 with no output. Failure means the envelope contract, regenerated patch, or Nix integration is incomplete. Do not run `just switch`.

- [ ] **Step 7: Commit**

```bash
git add \
  patches/agent-plugins/codex-plugin-cc.patch \
  lib/agent-plugins.nix \
  home/common/claude-code/skills/codex-collaboration/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-48): preserve review operation identity" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: signed commit succeeds and `git status --short` shows only files belonging to later tasks or pre-existing worktree artifacts.
