# Broker Reaping Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every `app-server-broker` process the codex-companion runtime spawns is reaped when its work is done — the suite reaps its own brokers immediately, a broker nobody wants exits on its own within a bounded interval, and every teardown that claims to clean up after a broker actually kills it.

**Architecture:** Three mechanisms for three failure modes, exactly as `.claude/specs/2026-08-12-broker-reaping-design.md` settled. (1) *Deterministic suite reaping*: every test file that writes under the state root pins `CLAUDE_PLUGIN_DATA` to a private temp root at module scope and a file-scoped `after` hook group-kills every broker recorded under that root. (2) *Broker self-supervision*: a pure decision module (`lib/broker-supervisor.mjs`) plus an `unref`'d interval inside the broker's `main()` that exits when the workspace's broker record no longer names this broker, or when nothing has connected for a bounded idle interval. (3) *Honest teardown*: `teardownBrokerSession` defaults `killProcess` to `terminateProcessTree` and force-removes files, and `ensureBrokerSession` refuses to reuse a broker recorded by a different plugin build. The plugin's code is not in this repo: all edits happen in a scratch clone of `openai/codex-plugin-cc` at pinned rev `db52e28f4d9ded852ab3942cea316258ae4ef346` and land here only as a regenerated `patches/agent-plugins/codex-plugin-cc.patch` plus a `patchRevision` bump 5 → 6. **Design authority: the spec. This plan implements it; it does not redesign it.**

**Tech stack:** Node ESM (`.mjs`, node builtins only), `node --test` + `node:assert/strict`, nix-darwin / home-manager (`just build`), zero-context git patch (`git apply --unidiff-zero` / `git diff -U0`).

---

## Global Constraints

- **The nix-store plugin copy is read-only.** Never edit anything under `/nix/store`. Never edit the plugin files in this repo — they do not exist here.
- **All plugin code edits happen in the scratch clone** at the fixed path below, and land in this repo **only** as `patches/agent-plugins/codex-plugin-cc.patch`. Never commit in the scratch clone.
- Upstream pin: `db52e28f4d9ded852ab3942cea316258ae4ef346`. Never change it.
- `patchRevision` in `lib/agent-plugins.nix` goes `5` → `6` **exactly once** (Task 2), never higher.
- **After creating any new file in the scratch clone, re-run `git add -N .` before regenerating the patch**, or the regenerated patch silently omits the file and the change ships broken. Every task that creates a file carries an explicit gate for this.
- Mandatory test command, run from the scratch clone root (the `env -u` scrub removes this machine's live Claude-session variables, without which 4 upstream tests fail spuriously):
  ```sh
  env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs
  ```
- `just build` (from the worktree) is this repo's **only** verification gate — there is no lint or test suite in this repo itself. Because the derivation runs `patch -p1 < ${patch}` over the whole upstream tree, a green `just build` is also the proof that the regenerated patch applies.
- Commits: worktree only, branch `worktree-issue-9-broker-reaping`. Every commit message ends with
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
  **Never disable commit signing** — no `-c commit.gpgsign=false`, no `--no-gpg-sign`. If signing fails, stop and report it.
- New identifiers follow the spec's Terminology: **broker record** for `broker.json`'s contents, **session** only for a Claude session, **owner/adopt** only for the session→broker relation, **`recorded`** (never "adopted") for the broker's own latch.
- Out of scope, binding (spec `## Out of scope`): issue #2's job-record machinery, `getSessionRuntimeStatus`'s label logic, `addOwner`'s no-session behavior, `sendBrokerShutdown`'s missing timeout, the dead `PID_FILE_ENV`/`LOG_FILE_ENV` exports, the 4 spuriously-failing upstream tests, any sweeper/GC daemon, session-id liveness probing, upstream contribution, and any CLAUDE.md change beyond R8's single sentence.

## Scratch checkout protocol

The scratch clone lives at a fixed absolute path and is **rebuilt deterministically from the currently committed patch at the start of every patch-touching task**, so tasks are independent and a half-edited tree can never leak between implementers.

```sh
SCRATCHPAD=/private/tmp/claude-502/-Users-anis-tmp-nix-config/05daa2af-9530-4c37-81eb-20624884fead/scratchpad
SCRATCH=$SCRATCHPAD/upstream
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-9-broker-reaping
```

Scratch logs and throwaway probes go under `$SCRATCHPAD`, never `/tmp` (which sibling agents share).

**Rebuild block** (run as Step 1 of Tasks 2–6):

```sh
# If $SCRATCH does not exist, create it first:
#   gh repo clone openai/codex-plugin-cc "$SCRATCH"
#   git -C "$SCRATCH" checkout --force --detach "$PIN"
git -C "$SCRATCH" reset --hard "$PIN"
git -C "$SCRATCH" clean -ffd
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" rev-parse HEAD   # must print db52e28f4d9ded852ab3942cea316258ae4ef346
```

`git apply --unidiff-zero` is required — the patch is zero-context and plain `git apply` rejects it.

**Regeneration block** (run near the end of Tasks 2–6):

```sh
git -C "$SCRATCH" add -N .     # MANDATORY: files created this task appear in the diff only after this
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```

Paths inside the scratch clone used by this plan:

- `$SCRATCH/plugins/codex/scripts/app-server-broker.mjs`
- `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`
- `$SCRATCH/plugins/codex/scripts/lib/broker-supervisor.mjs` (new)
- `$SCRATCH/plugins/codex/scripts/lib/process.mjs` (read only — `terminateProcessTree`, `isProcessAlive`)
- `$SCRATCH/tests/helpers.mjs`, `$SCRATCH/tests/fake-codex-fixture.mjs`
- `$SCRATCH/tests/broker-reaping.test.mjs` (new)
- `$SCRATCH/tests/runtime.test.mjs`, `state.test.mjs`, `liveness.test.mjs`, `reviewer-detach.test.mjs`

## Process-table measurement protocol

**Every process count in this plan uses `count` as defined here. A bare `pgrep -f … | wc -l` is not a valid instrument on this machine** — Task 1 measured both reasons:

- **Sibling agents run this same suite from their own scratch clones.** During Task 1 a concurrent agent's tree (`/tmp/codex-plugin-cc-issue-10-scratch`) went from 7 to 85 live brokers. An unscoped count drifts with their work, so a before/after comparison measures them, not you.
- **One unrelated `codex app-server` runs permanently** (a browser extension host, `~/.codex/plugins/.plugin-appserver/codex`, days of uptime). An unscoped app-server count therefore never reaches `0`, and any gate demanding it fails for that reason alone.

Attribution is by the process's **inherited `PWD`**, which is the scratch clone the suite was launched from — unique per agent, and still correct for an app-server whose broker has already died, which is exactly the case AC1 exists to catch (a pid-only kill satisfies `pgrep -f app-server-broker` while stranding the app-servers).

```sh
# Requires $SCRATCH. `ps -ww` (double -w) is mandatory: macOS ps truncates
# command lines to the terminal width, and these paths are ~200 chars, so a
# single -w silently mis-attributes your own processes as foreign.
mine() {   # mine <pgrep-pattern> -> pids whose PWD is this scratch clone
  for p in $(pgrep -f "$1"); do
    ps -Eww -o command= -p "$p" 2>/dev/null | tr ' ' '\n' \
      | grep -qxF "PWD=$SCRATCH" && echo "$p"
  done
}

count() { printf 'brokers=%s app-servers=%s\n' \
  "$(mine 'app-server-broker\.mjs serve' | grep -c .)" \
  "$(mine 'codex app-server' | grep -c .)"; }

reap_mine() {   # scoped TERM->KILL of this clone's brokers, taking their groups
  for p in $(mine 'app-server-broker\.mjs serve'); do
    kill -TERM "-$p" 2>/dev/null || kill -TERM "$p" 2>/dev/null
  done
  sleep 2
  for p in $(mine 'app-server-broker\.mjs serve'); do
    kill -KILL "-$p" 2>/dev/null || kill -KILL "$p" 2>/dev/null
  done
}
```

**Never `pkill -f 'app-server-broker.mjs serve'` or `pkill -f 'codex app-server'`.** Both patterns match sibling agents' processes and the extension host. Use `reap_mine`.

Because `count` is scoped, the gates below assert an **absolute `brokers=0 app-servers=0`** rather than a before/after equality — a stronger and simpler claim, and one that cannot be satisfied or broken by another agent's activity.

## File structure

| File | Responsibility |
|---|---|
| `lib/broker-supervisor.mjs` (new) | The supervision vocabulary: two env-var names + defaults, the strict positive-integer bound parser, record classification (`mine`/`foreign`/`missing`/`unreadable`), and the pure continue-or-exit decision. No timers, no processes, no filesystem. |
| `app-server-broker.mjs` | Accepts `--log-file`; resolves its record path once at startup; tracks connection count and last activity; latches `recorded`; runs the `unref`'d supervision interval inside `main()`; performs the exit sequence; `shutdown` unlinks the log file and `rmdir`s the broker session dir. |
| `lib/broker-lifecycle.mjs` | Records and gates on `scriptPath`; passes `--log-file` in `spawnBrokerProcess`; exports the lock-guarded "delete the record iff it names this endpoint"; `teardownBrokerSession` defaults `killProcess`, guards against a recycled pid, and force-removes files. |
| `tests/helpers.mjs` | Adds the hermetic-state-root-plus-reaper helper every state-writing test file calls once at module scope. |
| `tests/fake-codex-fixture.mjs` | Records the fake `codex app-server`'s own pid in its state file so tests can observe the broker's grandchild dying. |
| `tests/broker-reaping.test.mjs` (new) | All nine of the spec's tests plus the recycled-pid positive control, one behaviour-named file. |
| `patches/agent-plugins/codex-plugin-cc.patch` (worktree) | The only plugin-code artifact this repo carries. |
| `lib/agent-plugins.nix` (worktree) | `patchRevision = 5` → `6`. |
| `CLAUDE.md` (worktree) | R8: the one sentence claiming every test run leaks `codex-plugin-test-*` state dirs into the live plugin data dir. |

## Test seams

The spec agreed these four. Implementers test at these and nowhere else; a task that seems to need a new seam is a plan bug, not an implementer's call.

1. **The supervision policy functions** (`lib/broker-supervisor.mjs`) — called directly with fabricated inputs. No timers, no processes, no sleeps.
2. **The `broker-lifecycle.mjs` module API** — `ensureBrokerSession` with injected `scriptPath`, `env`, `timeoutMs`, `createBrokerEndpoint`; `teardownBrokerSession` called directly.
3. **A real spawned broker plus process liveness** — `spawnBrokerProcess` with the fake codex on `PATH`, asserting the process exits (bounded poll on `isProcessAlive`) and its files are gone.
4. **The companion CLI subprocess surface** — `node scripts/codex-companion.mjs review|task …` against a temp workspace with the fake codex installed, plus the on-disk broker record read through the exported resolvers.

Fixture rules: `makeTempDir` workspaces, `initGitRepo`, `installFakeCodex`, **production-shaped broker records** (full field set, not the shortest thing that parses), real detached processes for live/dead pids. **No call-count assertions and no spy on `killProcess` anywhere** — a killed process is observable, so observe it.

## Auto-resolved decisions

### Task granularity: seven tasks, five of them patch-touching
- **Question:** How is the spec's work split into tasks?
- **Choice:** Task 1 baseline guard (no commit); Tasks 2–6 one mechanism each, each ending in a green suite, a regenerated patch, a green `just build` and one worktree commit; Task 7 final evidence + the R8 doc correction.
- **Grounding:** `writing-plans` — "split only where a reviewer could meaningfully reject one task while approving its neighbor". A reviewer can reject the suite reaper while approving the teardown default, the build-identity gate while approving the decision table, and so on: they are four separate modules and four separate spec decisions (D-3, D-5, D-2, D-1). The sibling plan `.claude/plans/2026-08-11-detached-reviewer-bridge.md` uses the same shape (one mechanism per task, one worktree commit per task).
- **Alternative considered:** One task per spec decision section (D-1…D-7) — rejected: D-6 and D-7 have no independently falsifiable gate of their own and would have produced tasks whose verification was already true at their base commit. One giant task — rejected: no intermediate reviewer gate, and the suite would stay red for the whole change.

### Suite reaping ships first, not last
- **Question:** In what order do the three mechanisms land?
- **Choice:** Deterministic suite reaping (Task 2) before the teardown, build-identity and self-supervision work.
- **Grounding:** It is the issue's headline (AC1/AC2, the 514-broker report, exhausted swap) and it satisfies R1/R2 for every broker that reaches a saved record, so it is the tracer bullet. It is *not* sufficient on its own: `ensureBrokerSession`'s not-ready path returns without saving a record (`broker-lifecycle.mjs:212-222`), so a broker orphaned by a readiness timeout is invisible to a record-walking reaper and only Task 3 closes it. Step 8 is scoped accordingly. It also makes every *later* task's broker-spawning test self-cleaning: Tasks 3–6 each spawn real brokers, and without the reaper an aborted implementer run leaks a broker pair per test onto the developer's machine — the exact failure this issue exists to close.
- **Alternative considered:** Policy module first (bottom-up) — rejected: it leaves five tasks' worth of new broker-spawning tests leaking before the reaper exists, and it front-loads the one module with no user-visible effect.

### The scratch clone is rebuilt from the committed patch at every task start
- **Question:** Does the scratch clone persist across tasks, or is it rebuilt?
- **Choice:** Fixed path, rebuilt deterministically at the start of every patch-touching task: `reset --hard $PIN`, `clean -ffd`, `git apply --unidiff-zero <committed patch>`, `git add -N .`.
- **Grounding:** Every implementer subagent starts fresh with no memory of the previous task's tree, so correctness must never depend on prior task state. Exactly the protocol `.claude/plans/2026-08-11-detached-reviewer-bridge.md` used across three patch-touching tasks ("rebuilt deterministically at the start of every task from the currently committed patch"). Clone reuse is a network optimisation only.
- **Alternative considered:** Reuse the tree the previous task left behind — rejected: a half-edited or dirty tree silently poisons the next regeneration, and nothing would detect it.

### `patchRevision` bumps in Task 2, not Task 7
- **Question:** When does `patchRevision` go 5 → 6, given five patch-touching commits?
- **Choice:** Task 2, with the first regenerated patch. Tasks 3–6 leave it at 6; Task 7 verifies it is exactly 6.
- **Grounding:** `codexVersion` embeds `p${patchRevision}` and the derivation name embeds `codexVersion`, so bumping at the first content change keeps every intermediate commit's version string truthful (the-bar "Truthful terminal states" applied to version metadata). Same decision and same grounding as the two prior plans in `.claude/plans/`. It also matters for R5: the build identity *is* the store path, so an intermediate commit whose patch changed while its version string did not would be a genuinely wrong build identity.
- **Alternative considered:** Bump in the final task — rejected: four intermediate commits would claim `p5` while carrying different content.

### `just build` runs in every patch-touching task
- **Question:** Is one `just build` at the end enough?
- **Choice:** No — every task that regenerates the patch runs `just build` before committing.
- **Grounding:** the-bar "Verify before claiming done". The derivation applies the patch with `patch -p1`, which is a *different* applier from `git apply --unidiff-zero`; a hunk that git accepts and `patch(1)` rejects would otherwise surface four tasks later, with four commits to bisect. Builds after the first are largely cached. Sibling-plan precedent: "Each ends in a green suite, a green `just build`, and one worktree commit."
- **Alternative considered:** One build in Task 7 — rejected for the bisect cost above.

### The anti-omission gate is a grep, not a rebuild
- **Question:** How does a task prove the regenerated patch actually contains the files it created?
- **Choice:** After regenerating, grep the patch for a `b/<path>` header for **every** file the task created, and assert the count.
- **Grounding:** This is the single most likely way the change ships broken (a file created without a follow-up `git add -N .` is silently absent from `git diff -U0`). A round-trip rebuild does *not* catch it: rebuilding from a patch that omits a file yields a tree without the file, whose own regenerated diff matches the broken patch byte-for-byte. A grep for the file's own header is the only check that fails.
- **Alternative considered:** Rebuild-and-compare round trip — rejected as demonstrably blind to this exact bug. `git status --porcelain` in the scratch clone — rejected: intent-to-add makes a file look staged whether or not the patch was regenerated afterwards.

### The suite helper is named `pinHermeticStateRoot` and returns its reaper
- **Question:** What is the `tests/helpers.mjs` function called, and how does a test invoke the reaper directly (spec test 9)?
- **Choice:** `pinHermeticStateRoot(label)` → `{ root, reapBrokers }`. It pins `CLAUDE_PLUGIN_DATA`, deletes the two session variables, and registers `after(reapBrokers)` itself.
- **Grounding:** The name states the side effect, which a hook-style name (`useIsolatedStateRoot`) hides; the runtime's own naming is verb-first (`resolveStateRoot`, `createBrokerSessionDir`). Returning `reapBrokers` is what makes spec test 9 ("invoke the reaper, assert the pid is dead") possible without exporting a second symbol, and re-running it from the `after` hook is idempotent because it walks records that no longer exist.
- **Alternative considered:** Two exports (`pinStateRoot` + `reapRecordedBrokers`) — rejected: two call sites for one invariant, and a file could adopt the pin without the reaper, which is the bug.

### Tests observe the broker's `codex app-server` grandchild via a fixture pid field
- **Question:** R1/R3 count `codex app-server` processes too. How does a test learn the grandchild's pid?
- **Choice:** The fake codex records `appServerPid = process.pid` into its existing `fake-codex-state.json` on app-server boot; tests read it.
- **Grounding:** the-bar "Tests that can fail" — the grandchild's death must be *observed*, and the fixture already writes `appServerStarts` and `lastCodexHome` to that file for exactly this kind of observation, so this follows an established local pattern rather than inventing one. It also keeps the assertion portable.
- **Alternative considered:** `pgrep -P <brokerPid>` — rejected: a second, non-portable mechanism for a fact the fixture can simply state, and it races the broker's own exit (once the broker is gone, `-P` finds nothing whether the child died or was reparented).

### The broker logs when its supervision arms, so test 2 needs no sleep
- **Question:** Spec test 2 deletes the broker record and expects an `orphaned` exit — but that exit requires the `recorded` latch, and a delete that beats the first tick leaves the broker running until the idle bound. How does the test know the latch flipped, without sleeping?
- **Choice:** The broker writes one line to its log the first tick the record classifies as `mine` (`supervision: armed endpoint=…`); the test waits on that line before deleting the record.
- **Grounding:** the-bar "The log stream is the debugger" — "why did my broker vanish?" is unanswerable without knowing whether it ever saw its own record, so the line is diagnostics that earns its place independently of the test. the-bar "Root causes" forbids "a sleep to paper over a race", which is precisely what a fixed 2×interval wait would be. The broker's stdout/stderr *is* the log file (`spawnBrokerProcess` wires both to it), so this costs one `process.stderr.write` and no new plumbing.
- **Alternative considered:** Sleep 2× the configured interval — rejected as the papering-over the bar forbids, and flaky on a loaded machine. Have the test re-save and re-delete the record until the broker exits — rejected: it makes the test pass for a reason other than the one under test.

### The broker's own `shutdown` force-removes its files too
- **Question:** D-5 makes `teardownBrokerSession`'s file removals force-removals. Does the broker side change as well?
- **Choice:** Yes — the broker's `shutdown` uses `fs.rmSync(…, { force: true })` for the socket, pid file and log file. The broker session dir stays a non-recursive `rmdir` in a try/catch.
- **Grounding:** the-bar "Defense in depth" — both sides of the race are the same check-then-unlink window, and the broker side is the worse one to leave: an `ENOENT` thrown inside `shutdown` surfaces as an unhandled rejection in a SIGTERM handler, leaving the record naming a dead process. The directory keeps the conservative rule for the reason D-5 gives.
- **Alternative considered:** Change only teardown, as D-5 literally says — rejected: D-5's *reason* (a real concurrent-unlink window) applies symmetrically, and the spec's `## Module surface` already assigns the broker's `shutdown` extension to this change.

### The bound parser's tests ride in the decision-table test
- **Question:** D-4's strict parser throws on a bad value. Does that get a test, given the spec lists nine tests?
- **Choice:** Yes — two rows inside spec test 1 (a valid override is honoured; a non-positive-integer throws). No new test file, no new seam.
- **Grounding:** the-bar "Tests that can fail" — "when a guard's boundary is redundant with a filter upstream of it, delete the guard and ask which test turns red; if none does, the guard is untested". The parser lives in the same module and is exercised through the same seam 1 ("called directly with fabricated inputs"), so this is the same test, not a tenth one.
- **Alternative considered:** Leave the throw untested — rejected: it is the one behaviour D-4 chose *over* a silent fallback, so it is exactly the part that must not rot.

### An empty-string bound value throws rather than falling back
- **Question:** Is `CODEX_COMPANION_BROKER_IDLE_TIMEOUT_MS=""` "absent" or "invalid"?
- **Choice:** Invalid — only `undefined` selects the default.
- **Grounding:** D-4: "A bad value must not silently fall back to the default — it would produce a broker whose reaping behavior nobody can predict", and the-bar "Fail loud". One rule ("present ⇒ strictly parsed") has no branch to get wrong; an empty-string exemption is a second, invisible spelling of "unset".
- **Alternative considered:** Treat `""` as unset — rejected: it is the shape a broken shell interpolation produces, which is exactly when a loud failure is worth most.

### The three internal call sites pass `killProcess: options.killProcess`
- **Question:** How do the three `broker-lifecycle.mjs` call sites stop meaning "do not kill" without introducing a second home for the policy?
- **Choice:** They pass `killProcess: options.killProcess` (dropping `?? null`) and let `teardownBrokerSession`'s destructuring default supply `terminateProcessTree` when the property is `undefined`.
- **Grounding:** D-5 — "omitting the option now means 'use the default', not 'do not kill'", with one authoritative home for the policy (the-bar DRY). A JS destructuring default fires on `undefined`, so an injected value still wins and an explicit `null` still means "do not kill", which keeps the parameter as the injection seam it was meant to be.
- **Alternative considered:** `killProcess: options.killProcess ?? terminateProcessTree` at each site — rejected: three more homes for the policy, which is the defect being fixed. Removing the `killProcess` truthiness check — rejected by D-5 as no-benefit churn.

### The suite reaper keeps an explicit `killProcess: terminateProcessTree`
- **Question:** After Task 3 the default makes the helper's explicit argument redundant. Remove it?
- **Choice:** No. The helper passes it explicitly, with a comment saying it is the production instrument and not a test double.
- **Grounding:** Task 2 lands before the default exists, so it is required there; and D-5 keeps `session-lifecycle-hook.mjs`'s identically redundant explicit pass on the grounds that it "is not a second home for the policy, and touching it would widen the patch for no behavior change". Same reasoning, same answer.
- **Alternative considered:** Drop it in Task 3 — rejected as patch surface with no behaviour change, and it would make Task 2's commit depend on a later task.

### R8's evidence comes from a throwaway probe root, not the live plugin data dir
- **Question:** The CLAUDE.md sentence claims test runs leak `codex-plugin-test-*` dirs into `~/.claude/plugins/data/codex-nix-codex/state/`. How is its falsity observed, given the documented command *unsets* `CLAUDE_PLUGIN_DATA` so that path is never used?
- **Choice:** Reproduce the mechanism with `CLAUDE_PLUGIN_DATA=<throwaway probe dir>` (the two session variables still scrubbed) and count `codex-plugin-test-*` entries under `<probe>/state`: `> 0` at p5 (Task 1), `0` after Task 2 (re-measured in Task 7). Additionally confirm the real live dir gained nothing during Task 7's full run.
- **Grounding:** The leak is caused by an *inherited* `CLAUDE_PLUGIN_DATA` — verified in `lib/state.mjs`: `resolveStateRoot()` is `$CLAUDE_PLUGIN_DATA/state` or else `os.tmpdir()/codex-companion`. A probe root reproduces that exactly. Checked at plan time: the live dir currently holds 9 workspace dirs and **no** `codex-plugin-test-*` entries, so a before/after measurement against it would have no signal, while running the p5 suite against it to manufacture signal would deliberately pollute the user's real data dir.
- **Alternative considered:** Measure the real live dir before and after — rejected for both reasons above. Trust the code change without measurement — rejected: the spec is explicit that "the doc change follows the evidence, it does not precede it".

### `--log-file` ships inside the self-supervision task
- **Question:** D-6 is its own spec decision. Does it get its own task?
- **Choice:** No — it lands in Task 6, whose tests 2/3/4 assert "no socket, pid file, log file or broker session dir remains".
- **Grounding:** D-6 exists because "R3 is unsatisfiable without fixing this", and the spec's nine tests are the binding test strategy — a separate task would need either a tenth test (widening a binding input) or a hand-run manual check as its only gate. `writing-plans`: "Fold setup, configuration, scaffolding and documentation into the task whose deliverable needs them."
- **Alternative considered:** A separate task verified by extending tests 2/3/4 afterwards — rejected: it means writing three tests with deliberately incomplete assertions and amending them one task later, and the amendment is where a mistake hides.

### The broker derives its session dir instead of taking a new flag
- **Question:** The broker must `rmdir` its broker session dir. Does it get a `--session-dir` argument?
- **Choice:** No — it derives it from `path.dirname` of the pid file, else the log file, else the unix socket path.
- **Grounding:** `teardownBrokerSession` already derives the same directory the same way (`sessionDir ?? (pidFile ? path.dirname(pidFile) : logFile ? path.dirname(logFile) : null)`), so this follows the established local pattern; the-bar YAGNI on a third argument that carries no information the other two lack. All three artifacts live in one `mkdtemp` dir by construction (`createBrokerSessionDir`).
- **Alternative considered:** A `--session-dir` flag — rejected as a fourth argument for a derivable value, widening the patch and the broker's usage surface.

### Grandchild-death assertions use a bounded poll; broker-death assertions do not
- **Question:** Can a test assert `isProcessAlive(appServerPid) === false` immediately after the reaper returns?
- **Choice:** No — the `codex app-server` assertions use a bounded `waitFor`; the broker pid is asserted directly, because the reaper verifies that one before returning.
- **Grounding:** the-bar "Verify before claiming done" cuts both ways: the reaper's own post-condition is "the recorded broker pid is gone", which it establishes by polling and escalating, so a direct assertion there is honest. The grandchild is reaped by the kernel a moment later, and a direct assertion on it would be a stopwatch masquerading as a fact. AC1's "immediately" is measured at the suite level by `pgrep`, where a `SIGKILL`'d process no longer matches `-f`.
- **Alternative considered:** Have the reaper also enumerate and verify grandchildren — rejected: it does not know their pids without `pgrep -P`, which the fixture-pid decision already rejected.

### Tests are appended in task order, not spec-numbering order
- **Question:** The spec numbers nine tests. Must `tests/broker-reaping.test.mjs` list them in that order?
- **Choice:** No — each task appends its tests to the end of the file. Final file order is 9, 5, 6, 7, 8+control, 1, 2, 3, 4.
- **Grounding:** Tasks are read in isolation, and an implementer told to insert at a computed position in a file it has not read is being handed an avoidable failure mode. Node's test runner does not care, and each test is named for its behaviour (node shard: "named for the behaviour"), so the spec numbers never appear in the file.
- **Alternative considered:** Reserve numbered placeholder blocks — rejected: `writing-plans` forbids placeholders outright.

### Task 1 makes no commit
- **Question:** Every other task ends in a commit. What does the baseline guard commit?
- **Choice:** Nothing — it changes no file, and it says so explicitly.
- **Grounding:** Its deliverable is *evidence*: that the scratch baseline still reproduces the committed patch byte-identically, and that both p5 leak measurements are non-zero so the later gates can fail. Manufacturing a commit for it would mean inventing a file change nobody asked for (the-bar YAGNI).
- **Alternative considered:** Fold it into Task 2's Step 1 — rejected: the recovery procedure and the p5 baseline numbers are needed by Task 7 as well, and a fresh implementer that finds the baseline broken must stop rather than edit.

### Flow: this worktree is resumed from Phase 5, not rebuilt from Phase 1
- **Question:** A prior `--auto` run of `from-issue 9` ended after Phase 4, leaving this worktree clean with the spec and plan committed. `from-issue`'s Phase-0 pre-flight says a single *clean* matching worktree is an orphan to remove. Remove it and redo Phases 1–4, or resume?
- **Choice:** Resume in place from Phase 5. The branch `worktree-issue-9-broker-reaping` is kept, its two artifact commits stand, and the flow restarts at the standards review.
- **Grounding:** The pre-flight's remove-the-orphan rule targets an empty shell left by a run that exited before producing anything; the check exists to stop two sessions racing, and no second session is on this branch. What is actually here is 2267 lines of committed, grounded design: a spec carrying seven grill-round decisions (so Phase 3 ran) and a plan whose `## Requirement coverage` table binds R1–R8 to all seven tasks and to the issue's six acceptance criteria. `git merge-base HEAD origin/main` equals `origin/main`'s tip (`165a3b0`), so the base is still current and Phase 1's own requirement — branch from `origin/<integration-branch>` — already holds. No Phase-5 provenance section and no finding-ID entries exist in the plan, which fixes the resume point at Phase 5.
- **Alternative considered:** Discard the worktree and rerun Phases 1–4 per the literal pre-flight rule — rejected: it destroys work this flow cannot cheaply reproduce, and a second design pass would diverge from the spec the plan already implements, for no correctness gain. Deleting also contradicts the standing rule to inspect a delete target first and surface a mismatch instead of proceeding: the target contradicts the "orphan" description.

### B1: Task 2's Step 8 gate could go red for a hole Task 2 does not close
- **Question:** The reviewer found Task 2's Step 8 asserting an exact process-count equality that depends on two things Task 2 does not own. (i) `ensureBrokerSession`'s not-ready path returns without saving a record (`broker-lifecycle.mjs:212-222`), so a broker orphaned by a readiness timeout is invisible to a record-walking reaper and only Task 3 kills it. (ii) `reapBrokers` had no `try`/`catch` while calling p5's `existsSync`-then-unlink `teardownBrokerSession` (`broker-lifecycle.mjs:299-312`), a race the plan itself calls real — a throw would reject the `after` hook *and* strand every remaining broker in the loop.
- **Choice:** Kept the task order and fixed the gate and the reaper instead. `reapBrokers` now wraps each record in `try`/`catch` with `fs.rmSync` in a `finally`, collects failures, and reports them on stderr rather than throwing. Step 8 keeps **strict** equality for the AC2 single-test repro and, for the AC1 full-suite count, requires the implementer to classify any residue: a surviving broker outside a `codex-plugin-*-data-*` temp root is not the suite's; a `reapBrokers:` line in the log means the reaper saw it and failed, which is a Task 2 defect to fix; no such line means it was never recorded, which is Task 3's hole — record it as `NOTREADY_ORPHANS` and proceed. Task 7 Step 3 still demands strict equality on both commands. The plan's "satisfies R1/R2 on its own" claim is now scoped to brokers that reach a saved record.
- **Grounding:** Verified both legs against the live tree. The per-record `try`/`catch` is correct permanently, not just as an ordering workaround: a reaper walking N records must not abandon records 2..N because record 1 threw, and an `after` hook that rejects converts a cleanup failure into a suite failure while still leaking. The residue rule reads the diagnostic the same fix introduces, so it costs no new machinery.
- **Alternative considered:** The reviewer's first option — swap Tasks 2 and 3 so kill-by-default lands first. Rejected: it creates the mirror problem, because Task 3's own tests spawn real brokers and would leak with no reaper in place, and it means moving `pinHermeticStateRoot`, `waitFor`, `makeWorkspace`, `killGroupQuietly` and `spawnDetachedSleeper` between two ~250-line tasks. Also rejected: softening Step 8 to defer both counts to Task 7, which would leave the tracer-bullet task with no gate for its own acceptance criteria.

### S1: the dictated CLAUDE.md sentence was false before it was written
- **Question:** Task 7 Step 5 told the implementer to write "Every test file that writes under the state root calls `pinHermeticStateRoot`" and to credit that helper alone for leaving no surviving processes.
- **Choice:** Rewrote the dictated sentence to name the five files that adopt the helper, to state that `isolation.test.mjs` manages a root of its own and is deliberately left alone, and to attribute process cleanliness to the reaper *plus* kill-by-default teardown *plus* the broker's own idle exit.
- **Grounding:** `tests/isolation.test.mjs:15-30` sets `CLAUDE_PLUGIN_DATA` to its own temp dir per test, and spec D-3 excludes it by name ("`isolation.test.mjs` already pins and restores per test and is left alone"), so the original sentence was false on its face. from-issue's plan-prose ≠ code-prose rule: text the implementer copies verbatim into `CLAUDE.md` must describe how the code actually behaves. Step 5's existing reconcile-before-committing instruction is a backstop, not a licence to dictate a wrong sentence.
- **Alternative considered:** Leave it and rely on that reconcile instruction — rejected: Step 4's evidence would pass, so nothing would prompt the implementer to notice the file-set claim is wrong.

### S2: the exit-reason log line is deleted microseconds after it is written
- **Question:** `superviseTick` writes `supervision: exiting reason=…` and then `shutdown` does `fs.rmSync(logFile, { force: true })`, while the dictated comment claimed "The log is the only debugger for a process nobody is attached to."
- **Choice:** Kept the deletion and fixed the prose. The comment now says the line is readable for as long as the broker runs, that shutdown deletes the log because R3 requires a self-reaped broker to leave no artifacts, and that it is therefore a live-tail diagnostic rather than a post-mortem one.
- **Grounding:** R3's acceptance criterion is "exits on its own … leaving no artifacts", so persisting the reason somewhere durable would break the criterion — the deletion is required, and the comment was the wrong half. The plan's own tests already read the log the only way that works, polling it while the broker is still up (`waitFor(() => fs.readFileSync(broker.logFile, …).includes("supervision: armed"))`), then asserting the log is gone after exit.
- **Alternative considered:** Write the exit reason to a sibling file that survives — rejected: it is exactly the artifact R3 forbids, for a diagnostic nobody has asked for (YAGNI).

### S3: an unhandled rejection in the supervision tick could kill a live broker
- **Question:** `superviseTick` is driven by `void superviseTick()` from an interval with no `try`/`catch`, so any throw is an unhandled rejection.
- **Choice:** Split the two fault classes. A fault in the predicates (`readRecordState`, `classifyBrokerRecord`, `decideBrokerSupervision`) is caught, logged and costs one tick — the broker stays alive. A fault in `shutdown`, which happens only after the record has been deleted and the decision is committed, is caught, logged, and followed by `process.exit(0)` anyway.
- **Grounding:** Node aborts the process on an unhandled rejection by default, so a predicate bug would kill a broker that is still serving someone, and a `shutdown` throw would abandon cleanup half-done — leaving exactly the socket, pid file and log R3 promises are gone. The reviewer's stated consequence ("a record naming a dead pid") does not hold for the non-foreign path, since `deleteBrokerRecordIfEndpointMatches` runs *before* `shutdown`; the real consequences are the two above, and the fix is shaped to them.
- **Alternative considered:** One outer `try`/`catch` that clears `exiting` and retries everything — rejected: a persistently failing `shutdown` would then retry forever and keep the broker alive, which is the precise failure this issue exists to close. Exiting with a stray socket is the lesser evil.

### S4: kill-by-default introduces a group signal aimed at a possibly-recycled pid
- **Question:** Task 3 makes `teardownBrokerSession` kill by default, and `terminateProcessTree` signals the whole process **group** (`process.mjs:100-101`, `kill(-pid, SIGTERM)`). On the stale-record path the pid comes from a record that may be days old, so a recycled pid would take an unrelated group down — a hazard this change introduces, since p5 passed `null` there and killed nothing.
- **Choice:** Added a `pidFileNamesPid(pidFile, pid)` guard in front of the kill: skip only when the pid file exists **and** names a different pid. A missing or unparseable pid file does not skip. Added a positive-control test that pins the guard.
- **Grounding:** The broker writes its pid file early in `main()` but after Node bootstrap (`app-server-broker.mjs:68`), so the not-ready path can legitimately find no pid file for a child it certainly spawned, and R4 requires that child to die — which is why "absent" must mean "kill", not "skip", and why the reviewer's "absent or names a different pid" needed narrowing. `pidFile` is already a parameter, so the check costs one read. Task 3's existing stale-record test writes no pid file and its teardown test writes a matching one, so both still pass.
- **Alternative considered:** Probe process identity instead (start time, `/proc`, `ps -o lstart=`) — rejected: platform-specific for a race this narrow, when the broker already records its own pid on disk.

### D1: Task 4 rewrote `addOwner`, which the plan itself declares out of scope
- **Question:** The reviewer flagged Task 4's `addOwner` rewrite as having no consumer. Verification showed something stronger: p5's `addOwner` returns the session untouched when there is no session id (`broker-lifecycle.mjs:59-68`), while the rewrite always materialises `owners: [...]` — a change to "`addOwner`'s no-session behavior", which this plan's Global Constraints list as binding out of scope.
- **Choice:** Dropped the rewrite. Task 4 Step 4 now says to leave `addOwner` exactly as it is and records why the record contract is already uniform. Fixed the two places that had described the normalisation as a deliverable.
- **Grounding:** The rewrite was also inert: the spawn path already passes `owners: []` (`broker-lifecycle.mjs:233`), `releaseBrokerOwner` already reads `current.owners ?? []` (`:253`), and neither the new reuse gate nor `decideBrokerSupervision` reads `owners`, so Task 4's `assert.deepEqual(session.owners, [])` passes without it. A plan must not contradict its own binding scope line, and dropping code is the smaller, more reversible correction.
- **Alternative considered:** Keep the rewrite and delete the out-of-scope line — rejected: the line comes from the approved spec's `## Out of scope`, so removing it is a scope change the review stage may not make unilaterally.

### D2: the reaper test's record assertion could flake for the same reason as B1
- **Question:** Task 2's test asserts `assert.ok(record)` right after a successful `review`, but the live suite guards the same situation with `if (!loadBrokerSession(repo)) return;` (`runtime.test.mjs:1008, 2329`) — because the not-ready path returns without saving a record.
- **Choice:** Neither assert blindly nor skip. The test now retries `review` up to three times until a record appears and fails with a message naming the expiring 2 s readiness wait if none ever does.
- **Grounding:** Copying the upstream early-return guard would make the test vacuous — its entire subject is a real recorded broker, so a silent pass would assert nothing about the reaper. Retrying keeps it non-vacuous and removes the flake class, and it is the same root cause as B1, which is why both are fixed together rather than one masking the other.
- **Alternative considered:** Raise the readiness timeout for this test — rejected: the test drives the CLI as a subprocess, so it cannot pass `options.timeoutMs`, and no environment variable exposes the bound.

### Execution: the process count is scoped by inherited PWD, and `pkill` is banned
- **Question:** Task 1 executed and found the plan's verification instrument invalid on this machine. A concurrent agent runs the same suite from its own scratch clone (`/tmp/codex-plugin-cc-issue-10-scratch`, which grew from 7 to 85 live brokers during Task 1), so an unscoped `pgrep -f … | wc -l` measures their work as well as yours; and one unrelated `codex app-server` (a browser extension host, days of uptime) means an unscoped app-server count can never reach `0`. The plan's `pkill -f 'app-server-broker.mjs serve'` would also have killed that sibling agent's brokers outright.
- **Choice:** Added a *Process-table measurement protocol* to the plan header — `mine`, `count` and `reap_mine`, attributing every process by its inherited `PWD`, which is the scratch clone the suite was launched from. Banned `pkill` outright. Rewrote Task 1 Steps 2/5, Task 2 Step 8 and Task 7 Step 3 to use it, and turned their gates from a before/after equality into an absolute `brokers=0 app-servers=0`.
- **Grounding:** Verified `ps -Eww` exposes the environment here and that `PWD` partitions the population exactly: all 85 live brokers and 85 of the 86 app-servers reported `PWD=/tmp/codex-plugin-cc-issue-10-scratch`, and the one remaining app-server had no `PWD` at all (the extension host). `PWD` also survives the case AC1 exists to catch — an app-server orphaned by a pid-only kill keeps its inherited environment after its broker dies, whereas parent-based attribution loses it. Task 1 additionally found that macOS `ps` truncates command lines to terminal width, which had already mis-attributed its own leaked broker as foreign, so `-ww` is mandatory and is now stated in the protocol.
- **Alternative considered:** Attribute app-servers by parent pid — rejected: it cannot see a stranded app-server whose broker is gone, which is the precise failure the app-server count exists to detect. Also rejected: serialise against the sibling agent, which is not something this plan can enforce; and passing a unique `CLAUDE_PLUGIN_DATA` for the demo runs, which would change the very command the acceptance criteria name.

### Execution: the worktree is resumed mid-Phase-6 at Task 4, not rebuilt
- **Question:** A fresh `from-issue 9 --auto` run found the branch `worktree-issue-9-broker-reaping` already carrying nine commits — spec, plan, the Phase-5 review fixes, and the Task 2 and Task 3 implementation commits — with a clean working tree and no PR open. `from-issue`'s Phase-0 pre-flight says a single clean matching worktree is an orphan from a run that exited mid-flow and should be removed with its branch. Remove and restart from Phase 1, or resume?
- **Choice:** Resume in place, re-entering the existing worktree and restarting Phase 6 at Task 4. Nothing was deleted.
- **Grounding:** The pre-flight's remove rule targets orphans with no valuable state; the reason it can delete without asking is that a worktree at that point holds nothing a rerun would not reproduce. This one holds a reviewed plan and two verified implementation commits, so the rule's premise does not hold. Resumption was verified safe before any dispatch: the working tree is clean, `git log origin/main..HEAD` shows Tasks 2 and 3 only (`pinHermeticStateRoot` and `terminateProcessTree` present in the patch, `buildIdentity`/supervision absent), `patchRevision` is already at 6 as Task 2 requires, and the committed patch re-applies cleanly onto pin `db52e28f` — so the Task 4 rebuild block starts from exactly the state the plan expects.
- **Alternative considered:** Follow the pre-flight literally — `git worktree remove` plus `git branch -D`, then redo Phases 1–5. Rejected: it destroys nine commits including a plan that already absorbed a full standards review with seven dispositioned findings, and the redone artifacts would not be identical, so the discarded review would have to be repurchased. Also rejected: cherry-pick the existing commits onto a fresh branch, which changes SHAs for no benefit when the branch is already based on `origin/main` and clean.

### Execution: `killGroupQuietly` became the exported `killGroup`, and later task text follows
- **Question:** Task 3's review found the `killGroupQuietly` this plan dictates for `tests/broker-reaping.test.mjs` (Task 3's code block) body-identical to the module-private `killGroup` in `tests/helpers.mjs` — verbatim duplication of a logic block, which the review rubric treats as a defect even when the plan mandates it. The fix exported `killGroup(pid, signal)` and deleted the duplicate. That left Tasks 4 and 6 dictating calls to a helper that no longer exists.
- **Choice:** Accepted the deduplication, then corrected the *forward-looking* references: Task 6's three teardown lines now read `t.after(() => killGroup(broker.child.pid, "SIGKILL"))`. Tasks 3's and 4's already-executed code blocks keep their original `killGroupQuietly` text as the historical record of what those implementers were told; the divergence is recorded here and in the sdd ledger rather than by rewriting dispatched instructions.
- **Grounding:** Task 4's implementer hit exactly this and flagged it — it substituted `killGroup(pid, "SIGKILL")` because writing a second group-kill helper was forbidden by its brief, and the review confirmed the substitution matched the file's existing teardown idiom. Since task briefs are extracted from this plan verbatim, leaving Task 6's text stale would hand its implementer a call to an undefined function and cost a review round to rediscover the same thing.
- **Alternative considered:** Re-add a local `killGroupQuietly` wrapper so every task's dictated text stays literally true — rejected: it reintroduces the duplication the review removed. Also rejected: rewrite Tasks 3 and 4's blocks too, which would make the plan disagree with the briefs those implementers actually worked from.

## Standards review provenance

- **Reviewer:** Claude fallback (`reviewer` subagent, fresh context, read-only toolset).
- **Codex attempted first and failed:** `codex-collaboration` `plan-review` dispatched one isolated read-only Codex run (`codex-companion` present, so this was not a capability fallback). The bridge returned `CODEX_REVIEW_FAILURE:` after ~12.4 min with the job's recorded status and no `Blocking`/`Should fix`/`Discussion` output — failure class **timeout / no valid result**. Per the skill's contract that is a real Codex failure, so exactly one native fallback ran; Codex was not retried.
- **Base SHA reviewed:** `165a3b000c4945c1b79ddca69e25b88b388acf27` (worktree base = `origin/main`), plan at HEAD `2181774`.
- **Live pre-change code:** reviewed in a scratch clone of `openai/codex-plugin-cc` at pin `db52e28f4d9ded852ab3942cea316258ae4ef346` with the committed patch applied, verified byte-identical to `patches/agent-plugins/codex-plugin-cc.patch` at `patchRevision = 5`.
- **Focus:** none configured; standard review bar.
- **Dispositions:** 7 findings, **7 accepted, 0 rejected, 0 deferred** — 1 Blocking (B1), 4 Should-fix (S1–S4), 2 Discussion (D1, D2, both accepted; D1 promoted to should-fix after verification showed it contradicts a binding out-of-scope line). Two findings were applied with the reviewer's stated consequence corrected against the live code (S3, S4); see their entries.
- The reviewer additionally confirmed, with no finding required: the suite reaper cannot escape its private temp root (`state.mjs:87-101` resolves the root at call time, nothing memoises it at import); a root `after` from an imported helper still runs under `--test-name-pattern`; every task's claimed p5 failure genuinely fails at p5; Task 4's positive control is a real control; and the patch/`patchRevision` protocol is followed at every patch-touching task.

---

### Task 1: Baseline guard and p5 evidence

**Files:** none — **this task changes no files and makes no commit.** Its deliverable is evidence.

**Interfaces:**
- Consumes: nothing.
- Produces (report these numbers verbatim; Tasks 2 and 7 compare against them): `BROKERS_BEFORE`, `APPSERVERS_BEFORE`, `LEAK_AFTER_REPRO`, `PROBE_STATE_DIRS_P5`.

- [ ] **Step 1: Confirm the scratch clone reproduces the committed patch byte-identically**

```sh
SCRATCH=/private/tmp/claude-502/-Users-anis-tmp-nix-config/05daa2af-9530-4c37-81eb-20624884fead/scratchpad/upstream
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-9-broker-reaping

git -C "$SCRATCH" reset --hard "$PIN"
git -C "$SCRATCH" clean -ffd
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > /tmp/issue-9-baseline-regen.patch
diff /tmp/issue-9-baseline-regen.patch "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch" && echo BASELINE-IDENTICAL
```

Expected: `BASELINE-IDENTICAL`, and `git -C "$SCRATCH" rev-parse HEAD` prints the pin.

**If it is not identical, or `$SCRATCH` does not exist — recovery, then stop and report:**

```sh
rm -rf "$SCRATCH"
gh repo clone openai/codex-plugin-cc "$SCRATCH"
git -C "$SCRATCH" checkout --force --detach "$PIN"
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
```

Re-run the diff. If a fresh clone still does not reproduce the committed patch byte-identically, **do not edit anything** — the committed patch and the pin disagree, which is a finding that invalidates this plan's premise. Report it.

- [ ] **Step 2: Reap the pre-existing leak so later measurements mean something**

At plan time this machine carried **79** leaked brokers and **79** leaked app-servers (the spec recorded 39 of each a few hours earlier). The before-count is not zero and must not be assumed.

Define `mine`, `count` and `reap_mine` from the plan header's *Process-table measurement protocol*. Record the **unscoped** totals once, for the record, then work scoped from here on:

```sh
pgrep -f 'app-server-broker\.mjs serve' | wc -l   # record as BROKERS_BEFORE
pgrep -f 'codex app-server'             | wc -l   # record as APPSERVERS_BEFORE

count                                  # this clone's share of the above
reap_mine
count
```

Expected after the reap: `brokers=0 app-servers=0` from the **scoped** `count`. The unscoped totals will *not* be zero and are not supposed to be — they include sibling agents' trees and the extension host, which you must not touch.

- [ ] **Step 3: Show the broker-leak measurement can fail at p5**

```sh
(cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   node --test --test-name-pattern 'shared broker' tests/*.test.mjs)
count                                  # record as LEAK_AFTER_REPRO
```

Expected: **greater than zero** on both families — this is AC2's repro leaking at p5, and it is what proves Task 2's "unchanged" gate is not vacuous. If it prints `brokers=0 app-servers=0`, stop and report: the measurement has no signal and Task 2's gate would pass for the wrong reason.

- [ ] **Step 4: Show the state-dir leak measurement can fail at p5**

```sh
probe=$(mktemp -d)
(cd "$SCRATCH" && env -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   CLAUDE_PLUGIN_DATA="$probe" node --test --test-name-pattern 'shared broker' tests/*.test.mjs)
ls -1 "$probe/state" 2>/dev/null | wc -l      # record as PROBE_STATE_DIRS_P5
echo "$probe"                                  # note the path for Task 7
```

Expected: **greater than zero** — this is R8's claim reproduced. If it is zero, stop and report: R8's correction would have no evidence behind it.

- [ ] **Step 5: Leave the process table clean**

```sh
reap_mine
count
```

Expected: `brokers=0 app-servers=0` from the scoped `count`. Report all four recorded numbers. **No commit.**

---

### Task 2: Deterministic suite reaping (R1, R2)

Every test file that writes under the state root gets its own private state root and stops every broker recorded there at file teardown, so a suite run leaves the process table exactly as it found it.

**Files:**
- Modify (scratch): `$SCRATCH/tests/helpers.mjs`
- Modify (scratch): `$SCRATCH/tests/fake-codex-fixture.mjs`
- Modify (scratch): `$SCRATCH/tests/runtime.test.mjs`, `$SCRATCH/tests/state.test.mjs`, `$SCRATCH/tests/liveness.test.mjs`, `$SCRATCH/tests/reviewer-detach.test.mjs`
- Create (scratch): `$SCRATCH/tests/broker-reaping.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`

**Interfaces:**
- Consumes: `listBrokerSessions()`, `teardownBrokerSession({ endpoint, pidFile, logFile, sessionDir, pid, killProcess })`, `loadBrokerSession(cwd)` from `plugins/codex/scripts/lib/broker-lifecycle.mjs`; `isProcessAlive(pid)`, `terminateProcessTree(pid)` from `plugins/codex/scripts/lib/process.mjs`; `makeTempDir`, `run`, `initGitRepo` from `tests/helpers.mjs`; `buildEnv(binDir)`, `installFakeCodex(binDir, behavior)` from `tests/fake-codex-fixture.mjs`.
- Produces:
  - `tests/helpers.mjs`: `export function pinHermeticStateRoot(label: string): { root: string, reapBrokers: () => Promise<void> }` — pins `CLAUDE_PLUGIN_DATA` to a fresh temp dir, deletes `CODEX_COMPANION_SESSION_ID` and `CODEX_COMPANION_TRANSCRIPT_PATH`, and registers `after(reapBrokers)`. Call once at module scope.
  - `tests/fake-codex-fixture.mjs`: `fake-codex-state.json` gains `appServerPid` — the pid of the most recent `codex app-server` process the fixture started.
  - `tests/broker-reaping.test.mjs` exists and calls `pinHermeticStateRoot("broker-reaping")` at module scope.

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Rebuild block* from the plan header. Confirm `git -C "$SCRATCH" rev-parse HEAD` prints the pin.

- [ ] **Step 2: Write the failing test (spec test 9 — the reaper actually reaps)**

Create `$SCRATCH/tests/broker-reaping.test.mjs`:

```js
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { buildEnv, installFakeCodex } from "./fake-codex-fixture.mjs";
import { initGitRepo, makeTempDir, pinHermeticStateRoot, run } from "./helpers.mjs";
import { loadBrokerSession } from "../plugins/codex/scripts/lib/broker-lifecycle.mjs";
import { isProcessAlive } from "../plugins/codex/scripts/lib/process.mjs";

// State resolvers read CLAUDE_PLUGIN_DATA at call time and spawned CLI children
// inherit process.env (via buildEnv), so this pin gives the whole file — and
// every broker it starts — a private state root, and reaps every broker
// recorded there when the file ends. node --test runs each file in its own
// process; nothing leaks across files.
const { reapBrokers } = pinHermeticStateRoot("broker-reaping");

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(ROOT, "plugins", "codex", "scripts", "codex-companion.mjs");

async function waitFor(predicate, { timeoutMs = 10000, intervalMs = 25 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Timed out waiting for condition.");
}

function makeWorkspace() {
  const workspace = makeTempDir();
  initGitRepo(workspace);
  fs.writeFileSync(path.join(workspace, "README.md"), "hello\n");
  run("git", ["add", "README.md"], { cwd: workspace });
  run("git", ["commit", "-m", "init"], { cwd: workspace });
  fs.writeFileSync(path.join(workspace, "README.md"), "hello again\n");
  return workspace;
}

test("the suite reaper stops every broker recorded under the hermetic state root", async () => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);

  // ensureBrokerSession returns without saving a record when its 2 s readiness
  // wait expires (broker-lifecycle.mjs:212-222). The live suite tolerates that
  // with `if (!loadBrokerSession(repo)) return;` (runtime.test.mjs:1008, 2329),
  // but returning early here would make the test vacuous — its whole subject is
  // a real recorded broker. Retry instead, and fail loudly if none is ever
  // recorded.
  let record = null;
  for (let attempt = 1; attempt <= 3 && record === null; attempt += 1) {
    const review = run("node", [SCRIPT, "review"], { cwd: workspace, env: buildEnv(binDir) });
    assert.equal(review.status, 0, review.stderr);
    record = loadBrokerSession(workspace);
  }
  assert.ok(
    record,
    "no review recorded a broker in 3 attempts: the broker's 2 s readiness wait is expiring on this machine"
  );
  const brokerPid = record.pid;
  const appServerPid = JSON.parse(fs.readFileSync(path.join(binDir, "fake-codex-state.json"), "utf8")).appServerPid;
  assert.equal(Number.isFinite(brokerPid), true, "the broker record should carry a pid");
  assert.equal(Number.isFinite(appServerPid), true, "the fake codex should have recorded its app-server pid");
  assert.equal(isProcessAlive(brokerPid), true);

  await reapBrokers();

  // reapBrokers verifies the recorded pid itself before returning, so this is
  // asserted directly; the app-server grandchild is reaped by the kernel a
  // moment later, so that one gets a bounded poll.
  assert.equal(isProcessAlive(brokerPid), false);
  await waitFor(() => !isProcessAlive(appServerPid));
  assert.equal(loadBrokerSession(workspace), null);
  assert.equal(fs.existsSync(record.sessionDir), false);
});
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/broker-reaping.test.mjs`

Expected: FAIL — `pinHermeticStateRoot` is not exported by `./helpers.mjs` (`SyntaxError: The requested module './helpers.mjs' does not provide an export named 'pinHermeticStateRoot'`).

- [ ] **Step 4: Record the fake app-server's pid**

In `$SCRATCH/tests/fake-codex-fixture.mjs`, inside the generated script's app-server boot block, add the pid line next to the existing state writes:

```js
const bootState = loadState();
bootState.appServerStarts = (bootState.appServerStarts || 0) + 1;
bootState.appServerPid = process.pid;
bootState.lastCodexHome = process.env.CODEX_HOME || null;
saveState(bootState);
```

(The fixture source is a template literal — this snippet contains no `${`, so it is emitted verbatim.)

- [ ] **Step 5: Write the helper**

In `$SCRATCH/tests/helpers.mjs`, add the imports and the function. The existing exports (`makeTempDir`, `writeExecutable`, `run`, `initGitRepo`) stay unchanged.

```js
import { after } from "node:test";

import { listBrokerSessions, teardownBrokerSession } from "../plugins/codex/scripts/lib/broker-lifecycle.mjs";
import { isProcessAlive, terminateProcessTree } from "../plugins/codex/scripts/lib/process.mjs";

const REAP_POLL_MS = 25;
const REAP_TIMEOUT_MS = 2000;

function killGroup(pid, signal) {
  try {
    process.kill(-pid, signal);
  } catch {
    try {
      process.kill(pid, signal);
    } catch {
      // Already gone.
    }
  }
}

async function waitUntilGone(pid) {
  const deadline = Date.now() + REAP_TIMEOUT_MS;
  while (Date.now() < deadline && isProcessAlive(pid)) {
    await new Promise((resolve) => setTimeout(resolve, REAP_POLL_MS));
  }
}

// Gives the calling test file its own state root and leaves the process table
// as it found it: every broker recorded under that root is stopped when the
// file ends. Call once at module scope; the returned reapBrokers is what the
// file-scoped `after` hook runs, exposed so a test can drive it directly.
//
// The root is a private temp dir, which is what keeps this reaper unable to
// reach a real broker: under the documented scrubbed test command the shared
// state root is os.tmpdir()/codex-companion, where a developer's own
// plain-shell broker lives.
export function pinHermeticStateRoot(label) {
  const root = makeTempDir(`codex-plugin-${label}-data-`);
  process.env.CLAUDE_PLUGIN_DATA = root;
  delete process.env.CODEX_COMPANION_SESSION_ID;
  delete process.env.CODEX_COMPANION_TRANSCRIPT_PATH;

  async function reapBrokers() {
    // listStateDirs() resolves the root at call time and tests do repoint this
    // variable mid-file, so re-pin the captured root before walking it.
    process.env.CLAUDE_PLUGIN_DATA = root;
    const failures = [];
    for (const { stateFile, session } of listBrokerSessions()) {
      // One bad record must not strand the rest, and this runs in an `after`
      // hook: a rejection here is reported as a test failure while the
      // remaining brokers stay alive — the worst of both outcomes. At this
      // task's base commit teardownBrokerSession still does existsSync-then-
      // unlink, and the broker's own shutdown races it for the same paths, so
      // ENOENT here is expected rather than exceptional until Task 3 lands.
      try {
        const pid = Number.isFinite(session.pid) ? session.pid : null;
        // killProcess is the production instrument, not a test double: the same
        // group SIGTERM session end uses. Each broker holds a codex app-server
        // child, so a pid-only signal would strand one app-server per broker.
        teardownBrokerSession({
          endpoint: session.endpoint ?? null,
          pidFile: session.pidFile ?? null,
          logFile: session.logFile ?? null,
          sessionDir: session.sessionDir ?? null,
          pid,
          killProcess: terminateProcessTree
        });
        if (pid !== null) {
          await waitUntilGone(pid);
          if (isProcessAlive(pid)) {
            killGroup(pid, "SIGKILL");
            await waitUntilGone(pid);
          }
          if (isProcessAlive(pid)) {
            failures.push(`broker pid ${pid} survived SIGKILL`);
          }
        }
      } catch (error) {
        failures.push(`${stateFile}: ${error instanceof Error ? error.message : String(error)}`);
      } finally {
        fs.rmSync(stateFile, { force: true });
      }
    }
    // Surfaced, not thrown: every record has already been attempted, so the
    // caller learns about a broker that genuinely would not die without the
    // reaper having abandoned its remaining work.
    if (failures.length > 0) {
      process.stderr.write(`reapBrokers: ${failures.join("; ")}\n`);
    }
  }

  after(reapBrokers);
  return { root, reapBrokers };
}
```

- [ ] **Step 6: Verify the new test passes**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/broker-reaping.test.mjs`

Expected: PASS, 1 test.

- [ ] **Step 7: Adopt the helper in the four state-writing test files**

In `$SCRATCH/tests/runtime.test.mjs` — add `pinHermeticStateRoot` to the existing `./helpers.mjs` import and insert the call directly after the import block, before any `const`:

```js
// State resolvers read CLAUDE_PLUGIN_DATA at call time and spawned CLI children
// inherit process.env (via buildEnv), so this pin keeps every test in this file
// hermetic and reaps every broker the file starts. node --test runs each file in
// its own process; nothing leaks across files.
pinHermeticStateRoot("runtime");
```

In `$SCRATCH/tests/state.test.mjs` — same, with `pinHermeticStateRoot("state")`.

In `$SCRATCH/tests/liveness.test.mjs` — replace the hand-rolled three-line pin (`process.env.CLAUDE_PLUGIN_DATA = makeTempDir("codex-plugin-liveness-data-");` and the two `delete` statements) with `pinHermeticStateRoot("liveness");`, keeping the existing explanatory comment and adding one clause for the reaper. Drop `makeTempDir` from the import only if nothing else in the file uses it (it does — keep it).

In `$SCRATCH/tests/reviewer-detach.test.mjs` — same replacement, `pinHermeticStateRoot("reviewer-detach");`.

- [ ] **Step 8: Full suite green, and the process table unchanged (AC1, AC2)**

Define `mine`, `count` and `reap_mine` from the plan header's *Process-table measurement protocol* — do not use a bare `pgrep | wc -l`, and never `pkill`.

```sh
reap_mine                               # start from a clean slate
count                                   # must print brokers=0 app-servers=0

# Keep the suite output: the residue rule below reads it.
(cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   node --test tests/*.test.mjs) 2>&1 | tee "$SCRATCHPAD/issue-9-task2-suite.log"
count                                   # AC1

(cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   node --test --test-name-pattern 'shared broker' tests/*.test.mjs)
count                                   # AC2 — strict
```

Expected: suite green (0 failures). The **AC2 repro must print `brokers=0 app-servers=0`** — one workspace, one broker, and Task 1 measured `LEAK_AFTER_REPRO = brokers=1 app-servers=1` for that same command at p5 (scoped the same way), so this half of the gate can fail and is not negotiable.

The **AC1 full-suite count should be `0 0` too, but one residue class is not this task's to close.** If AC1 is non-zero, classify it before proceeding — do not soften the gate and do not proceed on a hunch. Because `count` is already scoped to this clone, every surviving process it reports is genuinely from your run:

```sh
for p in $(mine 'app-server-broker\.mjs serve'); do ps -ww -o pid=,command= -p "$p"; done
grep -c 'reapBrokers:' "$SCRATCHPAD/issue-9-task2-suite.log" || true
```

- If `reapBrokers:` appears in the suite log, the reaper saw that broker and failed to kill it. **That is a Task 2 defect — fix it before committing.**
- If no `reapBrokers:` line was emitted, the residue was never recorded, so no record-walking reaper could have found it: it is a broker `ensureBrokerSession` orphaned when its 2 s readiness wait expired before any record was saved (`broker-lifecycle.mjs:212-222`). **That is Task 3's hole, not Task 2's.** Record the count as `NOTREADY_ORPHANS`, report it, run `reap_mine`, and proceed.

Task 7 Step 3 re-asserts `brokers=0 app-servers=0` on **both** commands once Task 3's kill-by-default teardown has landed, which is where `NOTREADY_ORPHANS` must be `0`.

- [ ] **Step 9: R8 evidence — the probe root stays clean**

```sh
probe=$(mktemp -d)
(cd "$SCRATCH" && env -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   CLAUDE_PLUGIN_DATA="$probe" node --test --test-name-pattern 'shared broker' tests/*.test.mjs)
ls -1 "$probe/state" 2>/dev/null | wc -l
```

Expected: `0`. Task 1 recorded `PROBE_STATE_DIRS_P5 > 0` for the same command. Report both numbers.

- [ ] **Step 10: Regenerate the patch, prove the new file is in it, and bump `patchRevision`**

```sh
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
grep -c '^diff --git a/tests/broker-reaping.test.mjs b/tests/broker-reaping.test.mjs$' \
  "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```

Expected: `1`. A `0` means `git add -N .` did not cover the new file and the patch would ship without it.

Then in `$WORKTREE/lib/agent-plugins.nix` change `patchRevision = 5;` to `patchRevision = 6;` (line 6).

- [ ] **Step 11: Verify the repo builds**

Run: `cd "$WORKTREE" && just build`

Expected: success. This also proves the regenerated patch applies under `patch -p1`.

- [ ] **Step 12: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "$(cat <<'EOF'
feat(agent-plugins): reap every broker a test file spawns (#9)

Every test file that writes under the state root now pins CLAUDE_PLUGIN_DATA to
a private temp root and stops each broker recorded there at file teardown, so a
suite run leaves the process table as it found it. patchRevision 5 -> 6.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Teardown kills by default (R4)

A teardown that is asked to clean up after a broker actually kills it — group-wide, so the broker's `codex app-server` child goes too — and its file removals tolerate the broker's own concurrent shutdown.

**Files:**
- Modify (scratch): `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`
- Modify (scratch): `$SCRATCH/tests/broker-reaping.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: `pinHermeticStateRoot`, `makeTempDir`, `initGitRepo`, `run` from `tests/helpers.mjs`; `installFakeCodex`, `buildEnv` from `tests/fake-codex-fixture.mjs`; `isProcessAlive` from `lib/process.mjs`; the `waitFor` and `makeWorkspace` helpers already in `tests/broker-reaping.test.mjs`.
- Produces:
  - `teardownBrokerSession({ endpoint = null, pidFile, logFile, sessionDir = null, pid = null, killProcess = terminateProcessTree })` — omitting `killProcess` now means "kill"; passing `null` still means "do not kill"; the pid, log and socket removals are force-removals. The kill is skipped when `pidFile` exists and names a pid other than `pid` (recycled-pid guard); a missing or unparseable pid file does not skip it.
  - `ensureBrokerSession`'s not-ready and stale-record paths, and `releaseBrokerOwner`, pass `killProcess: options.killProcess` (no `?? null`).

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Rebuild block* from the plan header.

- [ ] **Step 2: Write the failing tests (spec tests 5, 6, 7)**

Append to `$SCRATCH/tests/broker-reaping.test.mjs`, and add these imports at the top of the file:

```js
import { spawn } from "node:child_process";

import {
  createBrokerSessionDir,
  ensureBrokerSession,
  saveBrokerSession,
  teardownBrokerSession
} from "../plugins/codex/scripts/lib/broker-lifecycle.mjs";
import { resolveStateDir } from "../plugins/codex/scripts/lib/state.mjs";
```

```js
function killGroupQuietly(pid) {
  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // Already gone.
    }
  }
}

function spawnDetachedSleeper(t) {
  const sleeper = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    detached: true,
    stdio: "ignore"
  });
  sleeper.unref();
  t.after(() => killGroupQuietly(sleeper.pid));
  return sleeper;
}

test("teardownBrokerSession kills the recorded broker process when no killProcess is passed", async (t) => {
  const sessionDir = createBrokerSessionDir();
  const pidFile = path.join(sessionDir, "broker.pid");
  const logFile = path.join(sessionDir, "broker.log");
  const sleeper = spawnDetachedSleeper(t);
  fs.writeFileSync(pidFile, `${sleeper.pid}\n`, "utf8");
  fs.writeFileSync(logFile, "broker log\n", "utf8");

  teardownBrokerSession({ endpoint: null, pidFile, logFile, sessionDir, pid: sleeper.pid });

  await waitFor(() => !isProcessAlive(sleeper.pid));
  assert.equal(fs.existsSync(pidFile), false);
  assert.equal(fs.existsSync(logFile), false);
  assert.equal(fs.existsSync(sessionDir), false);
});

test("the not-ready path terminates the broker it spawned and that broker's own child", async (t) => {
  const workspace = makeWorkspace();
  const reportDir = makeTempDir();
  const pidReport = path.join(reportDir, "pids.txt");
  const brokerStub = path.join(reportDir, "never-listens-broker.mjs");
  fs.writeFileSync(
    brokerStub,
    [
      'import fs from "node:fs";',
      'import { spawn } from "node:child_process";',
      '// Not detached: this child shares the stub broker\'s process group, so only',
      '// a group signal reaps it -- which is the behaviour under test.',
      'const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" });',
      'fs.writeFileSync(process.env.BROKER_STUB_PID_REPORT, `${process.pid}\\n${child.pid}\\n`, "utf8");',
      'setInterval(() => {}, 1000);',
      ""
    ].join("\n"),
    "utf8"
  );
  t.after(() => {
    if (!fs.existsSync(pidReport)) {
      return;
    }
    for (const pid of fs.readFileSync(pidReport, "utf8").trim().split("\n").map(Number)) {
      killGroupQuietly(pid);
    }
  });

  const session = await ensureBrokerSession(workspace, {
    scriptPath: brokerStub,
    env: { ...process.env, BROKER_STUB_PID_REPORT: pidReport },
    timeoutMs: 2000
  });

  assert.equal(session, null);
  assert.equal(fs.existsSync(pidReport), true, "the stub broker never reported its pid");
  const [stubPid, grandchildPid] = fs.readFileSync(pidReport, "utf8").trim().split("\n").map(Number);
  await waitFor(() => !isProcessAlive(stubPid));
  await waitFor(() => !isProcessAlive(grandchildPid));
});

test("the stale-record path terminates the broker whose endpoint no longer answers", async (t) => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const sleeper = spawnDetachedSleeper(t);
  const staleDir = createBrokerSessionDir();
  saveBrokerSession(workspace, {
    endpoint: `unix:${path.join(staleDir, "broker.sock")}`,
    pidFile: path.join(staleDir, "broker.pid"),
    logFile: path.join(staleDir, "broker.log"),
    sessionDir: staleDir,
    pid: sleeper.pid,
    stateDir: resolveStateDir(workspace),
    workspaceRoot: workspace,
    codexHome: path.join(staleDir, "codex-home"),
    owners: []
  });

  await ensureBrokerSession(workspace, { env: buildEnv(binDir), timeoutMs: 5000 });

  await waitFor(() => !isProcessAlive(sleeper.pid));
});

// Positive control for the recycled-pid guard. It passes at p5 for an
// uninteresting reason (p5 never kills at all) and would fail against a Task 3
// that defaults killProcess to a kill *without* the guard, which is the
// regression it exists to catch.
test("teardownBrokerSession does not signal a pid the pid file no longer claims", async (t) => {
  const sessionDir = createBrokerSessionDir();
  const pidFile = path.join(sessionDir, "broker.pid");
  const logFile = path.join(sessionDir, "broker.log");
  const survivor = spawnDetachedSleeper(t);
  // The caller still names `survivor`, but the pid file on disk names somebody
  // else — which is what a recycled pid looks like from the stale-record path.
  // terminateProcessTree signals the whole group, so guessing wrong here would
  // take an unrelated process group down.
  fs.writeFileSync(pidFile, `${survivor.pid + 1}\n`, "utf8");
  fs.writeFileSync(logFile, "broker log\n", "utf8");

  teardownBrokerSession({ endpoint: null, pidFile, logFile, sessionDir, pid: survivor.pid });

  assert.equal(isProcessAlive(survivor.pid), true, "the guard should have skipped this kill");
  // The files still go: the post-condition is "no artifacts", independent of
  // whether anything was signalled.
  assert.equal(fs.existsSync(pidFile), false);
  assert.equal(fs.existsSync(sessionDir), false);
});
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/broker-reaping.test.mjs`

Expected: **3 failures and 1 pass.** The three failures are each `Timed out waiting for condition.` — at p5 `killProcess` defaults to `null` and the three call sites pass `?? null`, so every one of those processes survives its teardown. `session === null` and the file assertions already pass at p5; the surviving process is the single reason each of the three fails. The fourth test (the recycled-pid guard) **passes at p5** and is labelled a positive control in the file: p5 kills nothing, so nothing to skip. If it ever fails, `pidFileNamesPid` is missing or wrong.

- [ ] **Step 4: Default `killProcess` and force-remove files**

In `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`, add the import:

```js
import { terminateProcessTree } from "./process.mjs";
```

(`lib/process.mjs` imports only node builtins, so there is no cycle.)

Replace `teardownBrokerSession`'s signature and its file removals:

```js
// terminateProcessTree signals the whole process *group* (kill(-pid, ...)), so a
// recycled pid would take an unrelated group down with it. That risk is real
// only for a pid read from a record that may be days old -- exactly when the
// stale-record path fires -- and this is where a kill first appears on that
// path, so the identity check belongs here.
//
// A missing pid file must NOT skip the kill: the broker writes it early in
// main() but after Node bootstrap, so the not-ready path can legitimately find
// no file for a child it definitely spawned, and R4 requires that child to die.
// Only a pid file that exists and names somebody else is evidence of recycling.
function pidFileNamesPid(pidFile, pid) {
  if (!pidFile) {
    return true;
  }
  let recorded;
  try {
    recorded = Number.parseInt(fs.readFileSync(pidFile, "utf8").trim(), 10);
  } catch {
    return true;
  }
  return !Number.isFinite(recorded) || recorded === pid;
}

// killProcess defaults to the production kill so that omitting it cannot mean
// "leave the broker running": a group SIGTERM, because a not-ready broker is
// usually still inside CodexAppServerClient.connect -- before its own SIGTERM
// handler is installed -- and only a group signal also reaps the codex
// app-server it already spawned. Pass null to skip the kill deliberately.
export function teardownBrokerSession({
  endpoint = null,
  pidFile,
  logFile,
  sessionDir = null,
  pid = null,
  killProcess = terminateProcessTree
}) {
  if (Number.isFinite(pid) && killProcess && pidFileNamesPid(pidFile, pid)) {
    try {
      killProcess(pid);
    } catch {
      // Ignore missing or already-exited broker processes.
    }
  }

  // Force removals, not existsSync-then-unlink: a SIGTERM'd broker runs its own
  // shutdown and unlinks these same paths concurrently, so the check-then-act
  // window is real. The post-condition is "the file is absent".
  if (pidFile) {
    fs.rmSync(pidFile, { force: true });
  }

  if (logFile) {
    fs.rmSync(logFile, { force: true });
  }

  if (endpoint) {
    try {
      const target = parseBrokerEndpoint(endpoint);
      if (target.kind === "unix") {
        fs.rmSync(target.path, { force: true });
      }
    } catch {
      // Ignore malformed or already-removed broker endpoints during teardown.
    }
  }

  const resolvedSessionDir = sessionDir ?? (pidFile ? path.dirname(pidFile) : logFile ? path.dirname(logFile) : null);
  if (resolvedSessionDir && fs.existsSync(resolvedSessionDir)) {
    try {
      fs.rmdirSync(resolvedSessionDir);
    } catch {
      // Ignore non-empty or missing directories.
    }
  }
}
```

- [ ] **Step 5: Stop the three internal call sites passing `null`**

In the same file, change `killProcess: options.killProcess ?? null` to `killProcess: options.killProcess` at all three sites: `ensureBrokerSession`'s stale-record teardown, `ensureBrokerSession`'s not-ready teardown, and `releaseBrokerOwner`'s teardown. A destructuring default fires on `undefined`, so omission now inherits the default while an injected value still wins.

Leave `session-lifecycle-hook.mjs` alone — its explicit `killProcess: terminateProcessTree` is now redundant but it is not a second home for the policy, and touching it would widen the patch for no behaviour change.

- [ ] **Step 6: Verify**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`

Expected: whole suite green — the three new tests pass, and the existing `SessionEnd`, `setup --cwd` and `shared broker` tests in `runtime.test.mjs` stay green (the `setup --cwd` test's hand-seeded record carries no `pid`, so `Number.isFinite(undefined)` keeps that path from killing anything).

- [ ] **Step 7: Regenerate the patch and build**

```sh
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
cd "$WORKTREE" && just build
```

Expected: `just build` succeeds. `patchRevision` stays `6` — do not touch `lib/agent-plugins.nix`.

- [ ] **Step 8: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "$(cat <<'EOF'
feat(agent-plugins): teardownBrokerSession kills the broker by default (#9)

killProcess defaults to terminateProcessTree and the three internal call sites
stop passing null, so the not-ready and stale-record paths terminate the broker
and its codex app-server child instead of deleting its files and walking away.
File removals become force-removals because the kill now races the broker's own
shutdown over the same paths.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Build identity in the reuse gate (R5)

`ensureBrokerSession` records which `app-server-broker.mjs` started a broker and refuses to reuse one from a different plugin build.

**Files:**
- Modify (scratch): `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`
- Modify (scratch): `$SCRATCH/tests/broker-reaping.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: `teardownBrokerSession`'s default `killProcess` (Task 3); `createBrokerEndpoint`, `parseBrokerEndpoint` from `lib/broker-endpoint.mjs`; `waitForBrokerEndpoint`, `createBrokerSessionDir`, `saveBrokerSession`, `ensureBrokerSession` from `lib/broker-lifecycle.mjs`.
- Produces: the broker record carries `scriptPath` (the absolute path of the `app-server-broker.mjs` that started it); `ensureBrokerSession` reuses a record only when `record.scriptPath` equals the script path it is about to use **and** the endpoint answers. `owners` is unchanged from p5 — the spawn path already seeds it with `[]`, so every record this task writes still carries one.

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Rebuild block* from the plan header.

- [ ] **Step 2: Write the failing test and its positive control (spec test 8)**

Append to `$SCRATCH/tests/broker-reaping.test.mjs`. Add to the existing imports: `createBrokerEndpoint` and `parseBrokerEndpoint` from `../plugins/codex/scripts/lib/broker-endpoint.mjs`, and `waitForBrokerEndpoint` from `../plugins/codex/scripts/lib/broker-lifecycle.mjs`. Add the `BROKER_SCRIPT` constant beside `SCRIPT`:

```js
const BROKER_SCRIPT = path.join(ROOT, "plugins", "codex", "scripts", "app-server-broker.mjs");

// A store path from an older patch revision: this is exactly the shape the
// record carries under a Nix-managed install, where the hash covers the whole
// patched tree and the name embeds the patch revision.
const FOREIGN_SCRIPT_PATH =
  "/nix/store/0000000000000000000000000000000000000000-codex-plugin-cc-1.0.6-nix.db52e28f.p4/plugins/codex/scripts/app-server-broker.mjs";

function startStubBroker(t, endpoint) {
  const target = parseBrokerEndpoint(endpoint);
  const source = `import net from "node:net"; net.createServer((socket) => socket.end()).listen(${JSON.stringify(
    target.path
  )}); setInterval(() => {}, 1000);`;
  const child = spawn(process.execPath, ["--input-type=module", "--eval", source], {
    detached: true,
    stdio: "ignore"
  });
  child.unref();
  t.after(() => killGroupQuietly(child.pid));
  return child;
}

function stubRecord(workspace, sessionDir, endpoint, pid, scriptPath) {
  return {
    endpoint,
    pidFile: path.join(sessionDir, "broker.pid"),
    logFile: path.join(sessionDir, "broker.log"),
    sessionDir,
    pid,
    stateDir: resolveStateDir(workspace),
    workspaceRoot: workspace,
    codexHome: path.join(sessionDir, "codex-home"),
    owners: [],
    scriptPath
  };
}

test("ensureBrokerSession retires a ready broker recorded by a different plugin build", async (t) => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const foreignDir = createBrokerSessionDir();
  const foreignEndpoint = createBrokerEndpoint(foreignDir);
  const stub = startStubBroker(t, foreignEndpoint);
  assert.equal(await waitForBrokerEndpoint(foreignEndpoint, 5000), true, "the stub broker never listened");
  saveBrokerSession(workspace, stubRecord(workspace, foreignDir, foreignEndpoint, stub.pid, FOREIGN_SCRIPT_PATH));

  const session = await ensureBrokerSession(workspace, { env: buildEnv(binDir), timeoutMs: 10000 });

  assert.ok(session, "a fresh broker should have replaced the foreign-build one");
  assert.notEqual(session.endpoint, foreignEndpoint);
  assert.equal(session.scriptPath, BROKER_SCRIPT);
  assert.deepEqual(session.owners, []);
  await waitFor(() => !isProcessAlive(stub.pid));
});

test("ensureBrokerSession reuses a ready broker recorded by this plugin build", async (t) => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const sessionDir = createBrokerSessionDir();
  const endpoint = createBrokerEndpoint(sessionDir);
  const stub = startStubBroker(t, endpoint);
  assert.equal(await waitForBrokerEndpoint(endpoint, 5000), true, "the stub broker never listened");
  saveBrokerSession(workspace, stubRecord(workspace, sessionDir, endpoint, stub.pid, BROKER_SCRIPT));

  const session = await ensureBrokerSession(workspace, { env: buildEnv(binDir), timeoutMs: 10000 });

  // Without this control, the test above passes trivially if reuse breaks
  // entirely.
  assert.equal(session.endpoint, endpoint);
  assert.equal(isProcessAlive(stub.pid), true);
});
```

- [ ] **Step 3: Run them and watch the first one fail**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/broker-reaping.test.mjs`

Expected: the "retires a ready broker recorded by a different plugin build" test FAILS at `assert.notEqual(session.endpoint, foreignEndpoint)` — at p5 the reuse gate is a 150 ms socket connect and nothing else, so the answering foreign-build stub is reused and its endpoint comes straight back. The positive control PASSES at p5 (reuse already works), which is what makes it a control.

- [ ] **Step 4: Record and gate on `scriptPath`**

In `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`:

**Leave `addOwner` exactly as it is.** An earlier draft rewrote it to always materialize `owners: [...]`; that is out of scope and unnecessary. p5's version returns the session untouched when there is no `CODEX_COMPANION_SESSION_ID` (`broker-lifecycle.mjs:59-68`), the spawn path already passes `owners: []` explicitly (`:233`), and `releaseBrokerOwner` already reads `current.owners ?? []` (`:253`), so the record contract every consumer sees is already uniform. Neither the reuse gate below nor `decideBrokerSupervision` reads `owners` at all.

Hoist the script-path resolution above the reuse check — it costs no IO, so the build check runs before the 150 ms socket probe — and gate reuse on it:

```js
export async function ensureBrokerSession(cwd, options = {}) {
  const stateDir = resolveStateDir(cwd);
  const scriptPath =
    options.scriptPath ?? fileURLToPath(new URL("../app-server-broker.mjs", import.meta.url));
  return withBrokerLock(stateDir, async () => {
    const existing = loadBrokerSession(cwd);
    // Under a Nix-managed install this path is a store path whose hash covers
    // the whole patched tree and whose name embeds the patch revision, so path
    // equality is build identity. A record written before this field existed
    // has no scriptPath and is therefore foreign, which retires it on first
    // contact with no migration code.
    const sameBuild = existing?.scriptPath === scriptPath;
    if (existing && sameBuild && (await isBrokerEndpointReady(existing.endpoint))) {
      const owned = addOwner(existing, options.env ?? process.env);
      saveBrokerSession(cwd, owned);
      return owned;
    }

    if (existing) {
      teardownBrokerSession({
        endpoint: existing.endpoint ?? null,
        pidFile: existing.pidFile ?? null,
        logFile: existing.logFile ?? null,
        sessionDir: existing.sessionDir ?? null,
        pid: existing.pid ?? null,
        killProcess: options.killProcess
      });
      clearBrokerSession(cwd);
    }
    // ... unchanged spawn path, minus the scriptPath const that moved up ...
```

Delete the now-duplicated `const scriptPath = options.scriptPath ?? fileURLToPath(...)` from the spawn path, and add `scriptPath` to the saved record:

```js
    const session = addOwner({
      endpoint,
      pidFile,
      logFile,
      sessionDir,
      pid: child.pid ?? null,
      stateDir,
      workspaceRoot: cwd,
      codexHome: runtime.runtimeHome,
      scriptPath,
      owners: []
    }, options.env ?? process.env);
```

- [ ] **Step 5: Verify**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`

Expected: whole suite green. In particular `runtime.test.mjs`'s `shared broker` test must stay green — both CLI invocations resolve the same default `scriptPath`, so reuse across them is unaffected — and so must the seeded endpoint-only record test that pins `getSessionRuntimeStatus` (it never calls `ensureBrokerSession`).

- [ ] **Step 6: Regenerate the patch and build**

```sh
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
cd "$WORKTREE" && just build
```

Expected: success. `patchRevision` stays `6`.

- [ ] **Step 7: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "$(cat <<'EOF'
feat(agent-plugins): refuse to reuse a broker from another plugin build (#9)

The broker record carries the scriptPath that started it, and ensureBrokerSession
reuses a record only when that path matches the one it is about to use. Records
written before this field existed carry none and are retired on first contact.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The supervision policy module (R3, decision table)

The orphan/idle decision as a pure function, so the decision table has a test that fails for exactly one reason and needs no stopwatch.

**Files:**
- Create (scratch): `$SCRATCH/plugins/codex/scripts/lib/broker-supervisor.mjs`
- Modify (scratch): `$SCRATCH/tests/broker-reaping.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: nothing beyond `node:process`.
- Produces (Task 6 imports exactly these):
  - `BROKER_IDLE_TIMEOUT_ENV = "CODEX_COMPANION_BROKER_IDLE_TIMEOUT_MS"`, `BROKER_SUPERVISE_INTERVAL_ENV = "CODEX_COMPANION_BROKER_SUPERVISE_INTERVAL_MS"`, `DEFAULT_BROKER_IDLE_TIMEOUT_MS = 600000`, `DEFAULT_BROKER_SUPERVISE_INTERVAL_MS = 15000`
  - `resolveSupervisionBounds(env = process.env) -> { idleTimeoutMs, superviseIntervalMs }`, throwing on a value that is not a positive integer
  - `classifyBrokerRecord({ present, record, endpoint }) -> "mine" | "foreign" | "missing" | "unreadable"`
  - `decideBrokerSupervision({ classification, recorded, connectionCount, lastActivityMs, nowMs, idleTimeoutMs }) -> { action: "continue" | "exit", reason: "replaced" | "orphaned" | "idle" | null }`

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Rebuild block* from the plan header.

- [ ] **Step 2: Write the failing test (spec test 1 — the decision table)**

Append to `$SCRATCH/tests/broker-reaping.test.mjs`, adding the import:

```js
import {
  BROKER_IDLE_TIMEOUT_ENV,
  BROKER_SUPERVISE_INTERVAL_ENV,
  DEFAULT_BROKER_IDLE_TIMEOUT_MS,
  DEFAULT_BROKER_SUPERVISE_INTERVAL_MS,
  classifyBrokerRecord,
  decideBrokerSupervision,
  resolveSupervisionBounds
} from "../plugins/codex/scripts/lib/broker-supervisor.mjs";
```

```js
const MINE = "unix:/tmp/cxc-mine/broker.sock";

function decide({ record, present = true, recorded = false, connectionCount = 0, idleForMs = 0, idleTimeoutMs = 1000 }) {
  return decideBrokerSupervision({
    classification: classifyBrokerRecord({ present, record, endpoint: MINE }),
    recorded,
    connectionCount,
    lastActivityMs: 10_000,
    nowMs: 10_000 + idleForMs,
    idleTimeoutMs
  });
}

function productionRecord(overrides = {}) {
  return {
    endpoint: MINE,
    pidFile: "/tmp/cxc-mine/broker.pid",
    logFile: "/tmp/cxc-mine/broker.log",
    sessionDir: "/tmp/cxc-mine",
    pid: 4242,
    stateDir: "/tmp/state/workspace-0123456789abcdef",
    workspaceRoot: "/tmp/workspace",
    codexHome: "/tmp/state/workspace-0123456789abcdef/codex-home",
    owners: [],
    scriptPath: "/tmp/plugins/codex/scripts/app-server-broker.mjs",
    ...overrides
  };
}

test("the supervision decision keeps a recorded broker with a live connection running", () => {
  assert.deepEqual(decide({ record: productionRecord(), recorded: true, connectionCount: 1, idleForMs: 999_999 }), {
    action: "continue",
    reason: null
  });
});

test("the supervision decision exits a broker whose record names a different endpoint", () => {
  assert.deepEqual(
    decide({ record: productionRecord({ endpoint: "unix:/tmp/cxc-other/broker.sock" }), recorded: true, connectionCount: 1 }),
    { action: "exit", reason: "replaced" }
  );
});

test("the supervision decision exits a broker whose record disappeared after it was recorded", () => {
  assert.deepEqual(decide({ present: false, record: null, recorded: true, connectionCount: 1 }), {
    action: "exit",
    reason: "orphaned"
  });
});

test("the supervision decision keeps a broker running while its record has never appeared", () => {
  // ensureBrokerSession writes the record only after readiness, so "missing"
  // is the expected state for a young broker.
  assert.deepEqual(decide({ present: false, record: null, recorded: false, connectionCount: 1 }), {
    action: "continue",
    reason: null
  });
});

test("the supervision decision keeps a broker running when its record does not parse", () => {
  // Only a definite absence justifies an exit; records are written by atomic
  // rename, so a parse failure is corruption, not a torn read.
  assert.deepEqual(decide({ present: true, record: null, recorded: true, connectionCount: 1 }), {
    action: "continue",
    reason: null
  });
});

test("the supervision decision exits an unconnected broker at exactly the idle bound", () => {
  assert.deepEqual(
    decide({ record: productionRecord(), recorded: true, connectionCount: 0, idleForMs: 1000, idleTimeoutMs: 1000 }),
    { action: "exit", reason: "idle" }
  );
});

test("the supervision decision keeps an unconnected broker running below the idle bound", () => {
  assert.deepEqual(
    decide({ record: productionRecord(), recorded: true, connectionCount: 0, idleForMs: 999, idleTimeoutMs: 1000 }),
    { action: "continue", reason: null }
  );
});

test("supervision bounds default when unset and are honoured when overridden", () => {
  assert.deepEqual(resolveSupervisionBounds({}), {
    idleTimeoutMs: DEFAULT_BROKER_IDLE_TIMEOUT_MS,
    superviseIntervalMs: DEFAULT_BROKER_SUPERVISE_INTERVAL_MS
  });
  assert.deepEqual(
    resolveSupervisionBounds({ [BROKER_IDLE_TIMEOUT_ENV]: "500", [BROKER_SUPERVISE_INTERVAL_ENV]: "100" }),
    { idleTimeoutMs: 500, superviseIntervalMs: 100 }
  );
});

test("a supervision bound that is not a positive integer throws instead of falling back", () => {
  for (const bad of ["0", "-1", "1.5", "abc", ""]) {
    assert.throws(
      () => resolveSupervisionBounds({ [BROKER_IDLE_TIMEOUT_ENV]: bad }),
      new RegExp(BROKER_IDLE_TIMEOUT_ENV),
      `expected ${JSON.stringify(bad)} to be rejected`
    );
  }
});
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/broker-reaping.test.mjs`

Expected: FAIL — `Cannot find module … lib/broker-supervisor.mjs`.

- [ ] **Step 4: Write the module**

Create `$SCRATCH/plugins/codex/scripts/lib/broker-supervisor.mjs`:

```js
import process from "node:process";

// Supervision policy for the app-server broker: the record vocabulary, the two
// bounds and the continue-or-exit decision. Pure by design -- no timers, no
// processes, no filesystem -- so the decision table is testable without a
// stopwatch and importing this module starts nothing. app-server-broker.mjs
// owns the tick, the counters and the exit sequence.

export const BROKER_IDLE_TIMEOUT_ENV = "CODEX_COMPANION_BROKER_IDLE_TIMEOUT_MS";
export const BROKER_SUPERVISE_INTERVAL_ENV = "CODEX_COMPANION_BROKER_SUPERVISE_INTERVAL_MS";

// Ten minutes is longer than any single bounded call in this runtime (during
// which a socket is connected, so the idle clock is not running) and short
// enough that an abandoned workspace releases its runtime within a coffee
// break. Production sets neither variable; they exist so the two
// self-termination behaviours have tests that finish in seconds.
export const DEFAULT_BROKER_IDLE_TIMEOUT_MS = 600000;
export const DEFAULT_BROKER_SUPERVISE_INTERVAL_MS = 15000;

const POSITIVE_INTEGER = /^[0-9]+$/;

function parseBoundMs(name, raw, fallback) {
  if (raw === undefined) {
    return fallback;
  }
  const value = Number(raw);
  if (!POSITIVE_INTEGER.test(raw) || !Number.isSafeInteger(value) || value <= 0) {
    // A silent fallback would produce a broker whose reaping behaviour
    // contradicts what the caller asked for, undetectable until it leaks.
    throw new Error(`${name} must be a positive integer number of milliseconds; received ${JSON.stringify(raw)}.`);
  }
  return value;
}

export function resolveSupervisionBounds(env = process.env) {
  return {
    idleTimeoutMs: parseBoundMs(BROKER_IDLE_TIMEOUT_ENV, env[BROKER_IDLE_TIMEOUT_ENV], DEFAULT_BROKER_IDLE_TIMEOUT_MS),
    superviseIntervalMs: parseBoundMs(
      BROKER_SUPERVISE_INTERVAL_ENV,
      env[BROKER_SUPERVISE_INTERVAL_ENV],
      DEFAULT_BROKER_SUPERVISE_INTERVAL_MS
    )
  };
}

// A broker record is "mine" iff it names the endpoint this broker was started
// with: each endpoint is a socket inside a fresh mkdtemp broker session dir, so
// it is already unique per broker and needs no extra identity field.
export function classifyBrokerRecord({ present, record, endpoint }) {
  if (!present) {
    return "missing";
  }
  if (record === null || typeof record !== "object") {
    return "unreadable";
  }
  return record.endpoint === endpoint ? "mine" : "foreign";
}

export function decideBrokerSupervision({
  classification,
  recorded,
  connectionCount,
  lastActivityMs,
  nowMs,
  idleTimeoutMs
}) {
  if (classification === "foreign") {
    // Whoever replaced the record already decided this broker is gone, so exit
    // even with a client connected -- it is unreachable by design now.
    return { action: "exit", reason: "replaced" };
  }
  if (classification === "missing" && recorded) {
    return { action: "exit", reason: "orphaned" };
  }
  if (connectionCount === 0 && nowMs - lastActivityMs >= idleTimeoutMs) {
    // The one criterion that covers every un-ownable case at once: unowned test
    // brokers, plain-shell CLI brokers, and brokers whose owning session died
    // without its SessionEnd hook running.
    return { action: "exit", reason: "idle" };
  }
  // Includes "unreadable": only a definite absence justifies an exit.
  return { action: "continue", reason: null };
}
```

- [ ] **Step 5: Verify**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`

Expected: whole suite green, including the 9 new decision-table tests.

- [ ] **Step 6: Regenerate the patch, prove the new module is in it, and build**

```sh
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
grep -c '^diff --git a/plugins/codex/scripts/lib/broker-supervisor.mjs b/plugins/codex/scripts/lib/broker-supervisor.mjs$' \
  "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
cd "$WORKTREE" && just build
```

Expected: the grep prints `1` (a `0` means `git add -N .` missed the new module and the patch would ship without it), and `just build` succeeds. `patchRevision` stays `6`.

- [ ] **Step 7: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "$(cat <<'EOF'
feat(agent-plugins): add the broker supervision policy module (#9)

lib/broker-supervisor.mjs owns the record classification vocabulary, the two
supervision bounds with a strict positive-integer parser, and the pure
continue-or-exit decision. No timers, no processes: the wiring lands next.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The broker supervises itself (R3)

The broker learns where its log file is, cleans up after itself completely, and exits on its own when its record no longer names it or nothing has connected for the idle bound.

**Files:**
- Modify (scratch): `$SCRATCH/plugins/codex/scripts/app-server-broker.mjs`
- Modify (scratch): `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`
- Modify (scratch): `$SCRATCH/tests/broker-reaping.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: `resolveSupervisionBounds`, `classifyBrokerRecord`, `decideBrokerSupervision` from `lib/broker-supervisor.mjs` (Task 5); `spawnBrokerProcess`, `saveBrokerSession`, `clearBrokerSession`, `loadBrokerSession`, `createBrokerSessionDir`, `waitForBrokerEndpoint`, `resolveBrokerStateFile` from `lib/broker-lifecycle.mjs`; `isProcessAlive` from `lib/process.mjs`; the fixture's `appServerPid`.
- Produces:
  - `spawnBrokerProcess` passes `--log-file <logFile>` alongside `--pid-file`.
  - `deleteBrokerRecordIfEndpointMatches(cwd, endpoint, options = {}) -> Promise<boolean>` in `lib/broker-lifecycle.mjs` — under the workspace's broker metadata lock, removes the record iff it still names `endpoint`; throws on lock timeout.
  - The broker accepts `--log-file`, writes `supervision: armed endpoint=…` to its log the first tick its record classifies as `mine`, and on exit writes `supervision: exiting reason=…`, deletes its own record when the record is still its own, and leaves no socket, pid file, log file or broker session dir behind.

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Rebuild block* from the plan header.

- [ ] **Step 2: Write the failing tests (spec tests 2, 3, 4)**

Append to `$SCRATCH/tests/broker-reaping.test.mjs`, adding `spawnBrokerProcess` and `clearBrokerSession` to the `broker-lifecycle.mjs` import:

```js
function makeCanonicalHome() {
  const canonicalHome = makeTempDir();
  fs.writeFileSync(path.join(canonicalHome, "auth.json"), "{}\n");
  fs.writeFileSync(path.join(canonicalHome, "config.toml"), 'model = "canonical"\n');
  return canonicalHome;
}

// Starts a real broker through the production spawn path, with the supervision
// bounds shortened so its self-termination is observable in seconds. buildEnv
// spreads process.env, so the file's pinned CLAUDE_PLUGIN_DATA reaches the
// broker and it resolves the same broker record this test writes.
function startSupervisedBroker({ workspace, binDir, canonicalHome, idleTimeoutMs, superviseIntervalMs }) {
  const sessionDir = createBrokerSessionDir();
  const endpoint = createBrokerEndpoint(sessionDir);
  const pidFile = path.join(sessionDir, "broker.pid");
  const logFile = path.join(sessionDir, "broker.log");
  const child = spawnBrokerProcess({
    scriptPath: BROKER_SCRIPT,
    cwd: workspace,
    endpoint,
    pidFile,
    logFile,
    env: {
      ...buildEnv(binDir),
      CODEX_HOME: canonicalHome,
      [BROKER_IDLE_TIMEOUT_ENV]: String(idleTimeoutMs),
      [BROKER_SUPERVISE_INTERVAL_ENV]: String(superviseIntervalMs)
    }
  });
  return { child, endpoint, pidFile, logFile, sessionDir };
}

function brokerRecord(workspace, broker, canonicalHome) {
  return {
    endpoint: broker.endpoint,
    pidFile: broker.pidFile,
    logFile: broker.logFile,
    sessionDir: broker.sessionDir,
    pid: broker.child.pid,
    stateDir: resolveStateDir(workspace),
    workspaceRoot: workspace,
    codexHome: canonicalHome,
    owners: [],
    scriptPath: BROKER_SCRIPT
  };
}

function appServerPidOf(binDir) {
  return JSON.parse(fs.readFileSync(path.join(binDir, "fake-codex-state.json"), "utf8")).appServerPid;
}

test("a live broker exits when its broker record disappears", async (t) => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const canonicalHome = makeCanonicalHome();
  const broker = startSupervisedBroker({
    workspace,
    binDir,
    canonicalHome,
    idleTimeoutMs: 60000,
    superviseIntervalMs: 100
  });
  t.after(() => killGroup(broker.child.pid, "SIGKILL"));

  assert.equal(await waitForBrokerEndpoint(broker.endpoint, 10000), true, "the broker never became ready");
  saveBrokerSession(workspace, brokerRecord(workspace, broker, canonicalHome));
  // The `recorded` latch is what separates "orphaned" from "not yet recorded",
  // so wait for the broker to say it has seen its own record before removing it.
  await waitFor(() => fs.readFileSync(broker.logFile, "utf8").includes("supervision: armed"));
  const appServerPid = appServerPidOf(binDir);

  clearBrokerSession(workspace);

  await waitFor(() => !isProcessAlive(broker.child.pid));
  await waitFor(() => !isProcessAlive(appServerPid));
  assert.equal(fs.existsSync(broker.pidFile), false);
  assert.equal(fs.existsSync(broker.logFile), false);
  assert.equal(fs.existsSync(parseBrokerEndpoint(broker.endpoint).path), false);
  assert.equal(fs.existsSync(broker.sessionDir), false);
  assert.equal(loadBrokerSession(workspace), null);
});

test("a live broker exits when its broker record is replaced, leaving the replacement alone", async (t) => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const canonicalHome = makeCanonicalHome();
  const broker = startSupervisedBroker({
    workspace,
    binDir,
    canonicalHome,
    idleTimeoutMs: 60000,
    superviseIntervalMs: 100
  });
  t.after(() => killGroup(broker.child.pid, "SIGKILL"));

  assert.equal(await waitForBrokerEndpoint(broker.endpoint, 10000), true, "the broker never became ready");
  saveBrokerSession(workspace, brokerRecord(workspace, broker, canonicalHome));
  await waitFor(() => fs.readFileSync(broker.logFile, "utf8").includes("supervision: armed"));

  const replacement = {
    ...brokerRecord(workspace, broker, canonicalHome),
    endpoint: "unix:/tmp/cxc-a-different-broker/broker.sock",
    pid: null
  };
  saveBrokerSession(workspace, replacement);

  await waitFor(() => !isProcessAlive(broker.child.pid));
  // An exiting broker must never delete a record that is not its own.
  assert.equal(loadBrokerSession(workspace).endpoint, replacement.endpoint);
  assert.equal(fs.existsSync(broker.sessionDir), false);
});

test("a live broker exits when nothing connects for the idle bound", async (t) => {
  const workspace = makeWorkspace();
  const binDir = makeTempDir();
  installFakeCodex(binDir);
  const canonicalHome = makeCanonicalHome();
  const broker = startSupervisedBroker({
    workspace,
    binDir,
    canonicalHome,
    idleTimeoutMs: 500,
    superviseIntervalMs: 100
  });
  t.after(() => killGroup(broker.child.pid, "SIGKILL"));
  saveBrokerSession(workspace, brokerRecord(workspace, broker, canonicalHome));

  await waitFor(() => !isProcessAlive(broker.child.pid), { timeoutMs: 15000 });

  // The record and the directory are what distinguish an idle self-exit from a
  // broker that simply failed to start.
  assert.equal(loadBrokerSession(workspace), null);
  assert.equal(fs.existsSync(broker.sessionDir), false);
});
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/broker-reaping.test.mjs`

Expected: 3 failures, all `Timed out waiting for condition.` — at p5 the broker has no timer of any kind, so the first two never log `supervision: armed` and the third never exits.

- [ ] **Step 4: Pass `--log-file` and export the record delete**

In `$SCRATCH/plugins/codex/scripts/lib/broker-lifecycle.mjs`, add the flag to the spawn argv:

```js
export function spawnBrokerProcess({ scriptPath, cwd, endpoint, pidFile, logFile, env = process.env }) {
  const logFd = fs.openSync(logFile, "a");
  const child = spawn(
    process.execPath,
    [scriptPath, "serve", "--endpoint", endpoint, "--cwd", cwd, "--pid-file", pidFile, "--log-file", logFile],
    {
      cwd,
      env,
      detached: true,
      stdio: ["ignore", logFd, logFd]
    }
  );
  child.unref();
  fs.closeSync(logFd);
  return child;
}
```

`detached: true` and `child.unref()` stay: outliving the spawning CLI process is the broker's entire purpose — what was missing was supervision, not attachment.

Add the export the broker's exit sequence uses:

```js
// The broker's own exit path: drop the record only while it still names this
// broker, so a broker that has already been replaced never deletes the new
// broker's record. Throws on lock timeout -- the caller retries on its next
// supervision tick.
export async function deleteBrokerRecordIfEndpointMatches(cwd, endpoint, options = {}) {
  const stateDir = resolveStateDir(cwd);
  return withBrokerLock(
    stateDir,
    async () => {
      const stateFile = resolveBrokerStateFile(cwd);
      const current = loadBrokerSessionFile(stateFile);
      if (!current || current.endpoint !== endpoint) {
        return false;
      }
      fs.rmSync(stateFile, { force: true });
      return true;
    },
    options.lockTimeoutMs ?? 5000
  );
}
```

- [ ] **Step 5: Wire the broker**

In `$SCRATCH/plugins/codex/scripts/app-server-broker.mjs`:

Add the imports:

```js
import { deleteBrokerRecordIfEndpointMatches, resolveBrokerStateFile } from "./lib/broker-lifecycle.mjs";
import {
  classifyBrokerRecord,
  decideBrokerSupervision,
  resolveSupervisionBounds
} from "./lib/broker-supervisor.mjs";
```

Extend the usage string and the parsed options, and resolve the bounds before anything is spawned so a bad value fails loud and early:

```js
  if (subcommand !== "serve") {
    throw new Error(
      "Usage: node scripts/app-server-broker.mjs serve --endpoint <value> [--cwd <path>] [--pid-file <path>] [--log-file <path>]"
    );
  }

  const { options } = parseArgs(argv, {
    valueOptions: ["cwd", "pid-file", "log-file", "endpoint"]
  });

  if (!options.endpoint) {
    throw new Error("Missing required --endpoint.");
  }

  // Before writePidFile and before the app-server is spawned: a bad bound must
  // not leave a half-started broker behind. Throwing here means the broker
  // never becomes ready, ensureBrokerSession returns null, and the CLI reports
  // that it failed to start the broker.
  const bounds = resolveSupervisionBounds(process.env);

  const cwd = options.cwd ? path.resolve(process.cwd(), options.cwd) : process.cwd();
  const endpoint = String(options.endpoint);
  const listenTarget = parseBrokerEndpoint(endpoint);
  const pidFile = options["pid-file"] ? path.resolve(options["pid-file"]) : null;
  const logFile = options["log-file"] ? path.resolve(options["log-file"]) : null;
  // Derived exactly as teardownBrokerSession derives it: the socket, pid file
  // and log file all live in one mkdtemp broker session dir.
  const brokerSessionDir = pidFile
    ? path.dirname(pidFile)
    : logFile
      ? path.dirname(logFile)
      : listenTarget.kind === "unix"
        ? path.dirname(listenTarget.path)
        : null;
  // resolveWorkspaceRoot shells out to git rev-parse, so this is resolved once
  // and never per tick.
  const brokerRecordFile = resolveBrokerStateFile(cwd);
  writePidFile(pidFile);
```

Extend `shutdown` so a stopped broker leaves nothing behind:

```js
  async function shutdown(server) {
    for (const socket of sockets) {
      socket.end();
    }
    // This awaits the codex app-server child's exit, so the broker takes its
    // app-server with it.
    await appClient.close().catch(() => {});
    await new Promise((resolve) => server.close(resolve));
    // Force removals: teardownBrokerSession may be unlinking these same paths
    // concurrently after signalling this process.
    if (listenTarget.kind === "unix") {
      fs.rmSync(listenTarget.path, { force: true });
    }
    if (pidFile) {
      fs.rmSync(pidFile, { force: true });
    }
    if (logFile) {
      fs.rmSync(logFile, { force: true });
    }
    if (brokerSessionDir) {
      try {
        fs.rmdirSync(brokerSessionDir);
      } catch {
        // Non-recursive on purpose: anything unexpected in the broker session
        // dir stays.
      }
    }
  }
```

Add the counters, the latch and the tick beside the existing socket state (`sockets` is already the connection set):

```js
  let recorded = false;
  let lastActivityMs = Date.now();
  let exiting = false;

  function markActivity() {
    lastActivityMs = Date.now();
  }

  function readRecordState() {
    if (!fs.existsSync(brokerRecordFile)) {
      return { present: false, record: null };
    }
    try {
      return { present: true, record: JSON.parse(fs.readFileSync(brokerRecordFile, "utf8")) };
    } catch {
      return { present: true, record: null };
    }
  }

  async function superviseTick() {
    if (exiting) {
      return;
    }
    let classification;
    let decision;
    // The only caller is `void superviseTick()` from an interval, so anything
    // escaping here is an unhandled rejection and Node aborts the process by
    // default. Aborting is the wrong answer while the broker may still be
    // serving somebody, so a fault in the predicates costs one tick.
    try {
      const { present, record } = readRecordState();
      classification = classifyBrokerRecord({ present, record, endpoint });
      if (classification === "mine" && !recorded) {
        recorded = true;
        // Before this line a missing record is the expected state, because
        // ensureBrokerSession writes the record only after readiness. This line
        // is readable for as long as the broker runs; shutdown deletes the log,
        // because R3 requires a self-reaped broker to leave no artifacts. It is
        // a live-tail diagnostic, never a post-mortem one -- which is why the
        // tests below poll the log while the broker is still up.
        process.stderr.write(`supervision: armed endpoint=${endpoint}\n`);
      }
      decision = decideBrokerSupervision({
        classification,
        recorded,
        connectionCount: sockets.size,
        lastActivityMs,
        nowMs: Date.now(),
        idleTimeoutMs: bounds.idleTimeoutMs
      });
    } catch (error) {
      process.stderr.write(
        `supervision: tick failed (${
          error instanceof Error ? error.message : String(error)
        }); retrying next tick\n`
      );
      return;
    }
    if (decision.action !== "exit") {
      return;
    }
    exiting = true;
    process.stderr.write(`supervision: exiting reason=${decision.reason} endpoint=${endpoint}\n`);
    if (classification !== "foreign") {
      try {
        await deleteBrokerRecordIfEndpointMatches(cwd, endpoint);
      } catch (error) {
        // ensureBrokerSession holds this lock for its whole body, so contention
        // is legitimate: retry on the next tick rather than dying and leaving a
        // record that names a dead process.
        process.stderr.write(
          `supervision: broker record lock unavailable (${
            error instanceof Error ? error.message : String(error)
          }); retrying next tick\n`
        );
        exiting = false;
        return;
      }
    }
    // The record is gone now, so the decision is committed and retrying is not
    // an option: a shutdown fault must not leave this broker running. Exit
    // regardless and accept a stray socket or log over an immortal broker,
    // which is the failure this whole mechanism exists to prevent.
    try {
      await shutdown(server);
    } catch (error) {
      process.stderr.write(
        `supervision: shutdown failed (${
          error instanceof Error ? error.message : String(error)
        }); exiting anyway\n`
      );
    }
    // A self-reap is not a failure.
    process.exit(0);
  }
```

Refresh the idle clock on every connection, every inbound line and every socket close/error. In the `net.createServer` callback add `markActivity();` right after `sockets.add(socket);`; inside the `data` handler's while-loop add `markActivity();` as the first statement of each line iteration; add `markActivity();` in both the `close` and `error` handlers.

Start the interval at the end of `main()`, next to `server.listen`:

```js
  // Started here, never at import: a module that starts a timer when it is
  // imported has no off switch. unref'd so supervision never keeps an
  // otherwise-finished process alive.
  const supervisionTimer = setInterval(() => {
    void superviseTick();
  }, bounds.superviseIntervalMs);
  supervisionTimer.unref();

  server.listen(listenTarget.path);
```

- [ ] **Step 6: Verify**

Run: `cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`

Expected: whole suite green — the three new tests pass and every existing broker test (`shared broker`, the two `SessionEnd` tests, `setup reuses an existing shared app-server`, all of `liveness.test.mjs`) stays green. The production defaults are 10 minutes and 15 seconds, so no existing test can be reaped mid-run by the new timer.

- [ ] **Step 7: Regenerate the patch and build**

```sh
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
cd "$WORKTREE" && just build
```

Expected: success. `patchRevision` stays `6`.

- [ ] **Step 8: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "$(cat <<'EOF'
feat(agent-plugins): give every broker a reason to stop existing (#9)

The broker re-reads its own workspace record on an unref'd interval and exits
when the record names a different endpoint, when the record it was once named by
is gone, or when nothing has connected for the idle bound -- deleting its record
only while it is still its own, and leaving no socket, pid file, log file or
broker session dir behind. spawnBrokerProcess passes --log-file so the broker can
remove the file that kept its directory alive.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Whole-issue verification and the CLAUDE.md correction (R6, R7, R8)

The acceptance-criteria demo on the finished code, then — and only then — the one documentation sentence the evidence makes false.

**Files:**
- Modify (worktree): `CLAUDE.md`
- Read only: `$SCRATCH`, `lib/agent-plugins.nix`, `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: Task 1's recorded `PROBE_STATE_DIRS_P5` and `LEAK_AFTER_REPRO`; the committed patch at `patchRevision = 6`.
- Produces: the corrected CLAUDE.md sentence, and the reported evidence.

- [ ] **Step 1: Rebuild the scratch checkout from the committed patch**

Run the *Rebuild block* from the plan header. This is also the final proof that the committed patch applies cleanly to a pristine pin tree.

- [ ] **Step 2: Confirm the repo-side artifacts**

```sh
cd "$WORKTREE"
grep -n 'patchRevision = ' lib/agent-plugins.nix
git status --porcelain
just build
```

Expected: `patchRevision = 6;` exactly (not 5, not 7), a clean working tree, and a successful build.

- [ ] **Step 3: The AC1 / AC2 demo**

Define `mine`, `count` and `reap_mine` from the plan header's *Process-table measurement protocol*.

```sh
reap_mine                               # start from a clean slate
count                                   # must print brokers=0 app-servers=0
(cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   node --test tests/*.test.mjs)
count                                   # AC1: must be brokers=0 app-servers=0

(cd "$SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   node --test --test-name-pattern 'shared broker' tests/*.test.mjs)
count                                   # AC2: must still be brokers=0 app-servers=0
```

Expected: the suite green (AC6), and **both** after-counts `brokers=0 app-servers=0` on **both** process families — this is where `NOTREADY_ORPHANS` from Task 2 must have gone to zero. Report the three counts verbatim. Task 1 measured `LEAK_AFTER_REPRO = brokers=1 app-servers=1` for the second command at p5, scoped identically, so this gate can fail.

- [ ] **Step 4: The R8 evidence**

```sh
before_live=$(ls -1 ~/.claude/plugins/data/codex-nix-codex/state/ 2>/dev/null | wc -l | tr -d ' ')
probe=$(mktemp -d)
(cd "$SCRATCH" && env -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   CLAUDE_PLUGIN_DATA="$probe" node --test tests/*.test.mjs)
ls -1 "$probe/state" 2>/dev/null | wc -l
ls -1 ~/.claude/plugins/data/codex-nix-codex/state/ 2>/dev/null | grep -c 'codex-plugin-test-' || true
ls -1 ~/.claude/plugins/data/codex-nix-codex/state/ 2>/dev/null | wc -l   # must equal $before_live
```

Expected: `0` state dirs under the probe root (Task 1 recorded `PROBE_STATE_DIRS_P5 > 0` for the same mechanism), `0` `codex-plugin-test-*` entries in the live plugin data dir, and the live dir's entry count unchanged.

**If any of these is non-zero, stop: do not edit CLAUDE.md.** The sentence is still true and the finding belongs in the report — the doc change follows the evidence, it does not precede it.

- [ ] **Step 5: Correct the one CLAUDE.md sentence**

Only after Step 4 passed. In `$WORKTREE/CLAUDE.md`, the `codex-plugin-cc` patch bullet currently ends:

```
… — with the live Claude-session env unscrubbed, 4 upstream tests fail spuriously and every test run leaks `codex-plugin-test-*` state dirs into `~/.claude/plugins/data/codex-nix-codex/state/`.
```

Replace that trailing clause with a description of what the code now does:

```
… — with the live Claude-session env unscrubbed, 4 upstream tests fail spuriously. The five test files that write under the shared state root (`runtime`, `state`, `liveness`, `reviewer-detach`, `broker-reaping`) call `pinHermeticStateRoot` (`tests/helpers.mjs`), which pins `CLAUDE_PLUGIN_DATA` to a private temp root and group-kills every broker recorded there at file teardown; `isolation.test.mjs` pins and restores a root of its own per test and is left alone. That, plus a `teardownBrokerSession` that kills by default and a broker that exits on its own once nothing wants it, is why a run deposits no `codex-plugin-test-*` state dirs in `~/.claude/plugins/data/codex-nix-codex/state/` and leaves no surviving `app-server-broker` or `codex app-server` processes.
```

Leave the "4 upstream tests fail spuriously" clause exactly as it is — that claim is out of scope and was not measured. Change nothing else in CLAUDE.md.

**Before committing, reconcile this sentence with what you actually observed.** If Step 4's evidence differs in any way from what this text asserts — a different helper name, a different mechanism, brokers surviving under some condition — rewrite the sentence to match the observed behaviour and say so in your report. Plan prose is not permission to describe code that does not behave that way.

- [ ] **Step 6: Verify the doc change did not break evaluation**

Run: `cd "$WORKTREE" && just build`

Expected: success. (`CLAUDE.md` is not a Nix input, so this is a cheap confirmation that the tree is still buildable — a failure here means something other than the sentence changed.)

- [ ] **Step 7: Commit**

```bash
cd "$WORKTREE"
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: the plugin suite no longer leaks state dirs or brokers (#9)

Corrected after observation: a full env-scrubbed suite run leaves the process
table unchanged on both process families, and a run with an inherited
CLAUDE_PLUGIN_DATA deposits no codex-plugin-test-* state dirs under it.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Requirement coverage

| Req | Acceptance criterion | Task |
|---|---|---|
| R1 | Full scrubbed suite run leaves zero additional brokers and zero additional orphaned app-servers | 2 (mechanism, Step 8) · 7 (final demo, Step 3) |
| R2 | `--test-name-pattern 'shared broker'` leaves zero additional brokers | 2 (Step 8) · 7 (Step 3) |
| R3 | A broker whose record is gone or replaced, or that nothing has connected to for the idle bound, exits on its own leaving no artifacts and taking its app-server with it | 5 (decision table) · 6 (wiring, `--log-file`, exit sequence) |
| R4 | `ensureBrokerSession`'s not-ready and stale-record paths terminate the child and its own child | 3 |
| R5 | A broker recorded by a different plugin build is retired, not reused; pre-change records count as foreign | 4 |
| R6 | The scrubbed suite passes, including new tests that fail at p5 for R3, R4, R5 | 3 (tests 5/6/7 fail at p5) · 4 (test 8 fails at p5) · 6 (tests 2/3/4 fail at p5) · 7 (final green) |
| R7 | Patch regenerated, `patchRevision` 5 → 6, `just build` green | 2 (bump) · 3–6 (regeneration + build) · 7 (final verification) |
| R8 | The CLAUDE.md leak sentence corrected once the suite is observed leaving the live plugin data dir clean | 7 (evidence in Step 4, edit in Step 5) |
