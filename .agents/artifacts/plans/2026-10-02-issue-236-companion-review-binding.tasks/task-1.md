# Task 1: Companion runtime report (patched codex-plugin-cc)

**Files:**
- Modify: `patches/agent-plugins/codex-plugin-cc.patch` (regenerated, never hand-edited)
- Modify: `lib/agent-plugins.nix` (`patchRevision = 12;` → `patchRevision = 13;`)
- Source edited in the scratch clone only: `plugins/codex/scripts/lib/codex.mjs`, `plugins/codex/scripts/codex-companion.mjs`, `tests/fake-codex-fixture.mjs`, `tests/reviewer-detach.test.mjs`

**Interfaces:**
- Consumes: the pinned upstream `db52e28f4d9ded852ab3942cea316258ae4ef346` plus the current patch.
- Produces, for Tasks 2–4: every `codex-companion task --json` payload gains `runtime: { model, reasoningEffort }`. Both values are copied verbatim from the `thread/start` or `thread/resume` response's top-level `model` and `reasoningEffort`, with `null` for an absent value. The existing keys `status`, `threadId`, `rawOutput`, `touchedFiles` and `reasoningSummary` are unchanged.

**Invariants:**
- On a fresh thread with a requested effort, the `thread/start` params carry `config: { model_reasoning_effort: <effort> }`. Without an effort they carry no `config` key at all, and `thread/resume` params never carry one (per D10).
- The `turn/start` request is unchanged and still sends `effort`.
- With no `--prompt-file` and no positional, a stdin packet is the turn's prompt (`readTaskPrompt` is unchanged; the test pins it, per D4).
- The rendered (non-JSON) output is unchanged.

## Setup

- [ ] **Step 0: Scratch clone at the pin, with the current patch applied**

```bash
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/cpcc-XXXXXX")"
git clone -q https://github.com/openai/codex-plugin-cc "$SCRATCH/cpcc"
cd "$SCRATCH/cpcc"
git checkout -q db52e28f4d9ded852ab3942cea316258ae4ef346
git apply --unidiff-zero <worktree>/patches/agent-plugins/codex-plugin-cc.patch
```

Record the baseline before touching anything:
`env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs 2>&1 | grep -E '^# (pass|fail)'`. Expected: `# fail 0`. Note the `# pass` count.

All of Steps 1–4 run inside `$SCRATCH/cpcc`.

- [ ] **Step 1: Write the failing tests** at the end of `tests/reviewer-detach.test.mjs`. That file already pins a hermetic state root and defines `makeReviewRepo`, `makeCanonicalHome` and `SCRIPT`.

```js
for (const operation of ["plan-review", "diff-review"]) {
  test(`a foreground ${operation} takes its stdin packet as the prompt and reports the runtime selection`, () => {
    const repo = makeReviewRepo();
    const binDir = makeTempDir();
    const canonicalHome = makeCanonicalHome();
    installFakeCodex(binDir);
    const env = { ...buildEnv(binDir), CODEX_HOME: canonicalHome };
    const packet = `# ${operation} packet\nRead the artifact at HEAD and report findings.\n`;

    const ran = run(
      "node",
      [SCRIPT, "task", "--fresh", "--reviewer", operation,
        "--model", "gpt-6-astra", "--effort", "xhigh", "--cwd", repo, "--json"],
      { cwd: repo, env, input: packet }
    );
    assert.equal(ran.status, 0, ran.stderr);
    const payload = JSON.parse(ran.stdout);
    assert.equal(payload.status, 0);
    assert.deepEqual(payload.touchedFiles, []);
    assert.deepEqual(payload.runtime, { model: "gpt-6-astra", reasoningEffort: "xhigh" });
    assert.equal(payload.rawOutput, "Handled the requested task.\nTask prompt accepted.");

    const fakeState = JSON.parse(fs.readFileSync(path.join(binDir, "fake-codex-state.json"), "utf8"));
    // The packet, not an argument tail, is the thread's first prompt.
    assert.equal(fakeState.lastTurnStart.prompt, packet.trim());
    assert.deepEqual(fakeState.lastThreadStart.config, { model_reasoning_effort: "xhigh" });
  });
}

test("a task with no requested effort sends no thread config and reports the runtime as returned", () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  installFakeCodex(binDir);

  const ran = run("node", [SCRIPT, "task", "--json", "investigate the failing test"], {
    cwd: repo,
    env: buildEnv(binDir)
  });
  assert.equal(ran.status, 0, ran.stderr);
  const payload = JSON.parse(ran.stdout);
  assert.deepEqual(payload.runtime, { model: "gpt-5.4", reasoningEffort: null });

  const fakeState = JSON.parse(fs.readFileSync(path.join(binDir, "fake-codex-state.json"), "utf8"));
  assert.equal(Object.hasOwn(fakeState.lastThreadStart, "config"), false);
});
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/reviewer-detach.test.mjs 2>&1 | tail -20`
Expected: 3 new failures. `payload.runtime` is `undefined`, and `lastThreadStart.config` is `undefined`.

- [ ] **Step 3: Implement**

1. `tests/fake-codex-fixture.mjs`: in the `thread/start` reply only, replace `reasoningEffort: null` with `reasoningEffort: message.params.config?.model_reasoning_effort ?? null`. The `thread/resume` reply keeps `reasoningEffort: null`. (The fixture is JS source emitted inside a template string, so keep its existing escaping.)
2. `plugins/codex/scripts/lib/codex.mjs`, `buildThreadParams`: add `config` only when `options.config` is a non-null object, e.g. `...(options.config ? { config: options.config } : {})`. `buildResumeParams` is untouched.
3. `runAppServerTurn`: in the fresh-thread branch, pass `config: options.effort ? { model_reasoning_effort: options.effort } : null` to `startThread`. In both branches, keep the response and record `runtime = { model: response.model ?? null, reasoningEffort: response.reasoningEffort ?? null }`. Add `runtime` to the returned object.
4. `plugins/codex/scripts/codex-companion.mjs`, `executeTaskRun`: add `runtime: result.runtime` to `payload`, after `reasoningSummary`. Nothing else changes, and `renderTaskResult` gets nothing new.

- [ ] **Step 4: Run the full plugin suite**

Run: `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs 2>&1 | grep -E '^# (tests|pass|fail)'`
Expected: `# fail 0`, and `# pass` is 3 higher than the count at Step 0.

- [ ] **Step 5: Regenerate the patch and bump the revision**

```bash
git -C "$SCRATCH/cpcc" diff -U0 db52e28f4d9ded852ab3942cea316258ae4ef346 > <worktree>/patches/agent-plugins/codex-plugin-cc.patch
```

Stage any new untracked file in the clone before diffing (`git add -N`). There should be none: every source file already exists. Then set `patchRevision = 13;` in `lib/agent-plugins.nix`.

- [ ] **Step 6: Verify against the built store path, not the patch text**

Run from the worktree:

```bash
just build 2>&1 | tail -3
STORE=$(nix-store -qR "$(readlink -f result)" | grep -- '-codex-plugin-cc-.*-nix\.db52e28f\.p13$')
test "$(printf '%s\n' "$STORE" | grep -c .)" -eq 1
grep -c 'model_reasoning_effort' "$STORE/plugins/codex/scripts/lib/codex.mjs"         # >= 1
grep -c 'runtime: result.runtime' "$STORE/plugins/codex/scripts/codex-companion.mjs"  # exactly 1
```

The build must succeed. `$STORE` is the marketplace that `lib/agent-plugins.nix` builds, named `codex-plugin-cc-<version>`, where the version ends `.p13`. `$STORE` is taken from this build's closure and must be exactly one path, so an earlier `.p13` build with different patch content cannot satisfy the gate. No `.p13` path exists at the base commit, and neither string is in the base source, so this gate can fail.

- [ ] **Step 7: Commit (in the worktree)**

```bash
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "feat(codex-plugin): report thread runtime selection in task --json (#236)"
```
