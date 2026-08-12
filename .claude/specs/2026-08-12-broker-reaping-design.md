# Design: Every app-server broker has a reaper; no broker outlives its usefulness

Issue: https://github.com/fagenorn/nix-config/issues/9 · Base: codex-plugin-cc pinned at `db52e28f`, patch p5 · Worktree branch: `worktree-issue-9-broker-reaping`

## Problem

Every `app-server-broker` process the codex-companion runtime spawns is potentially immortal. The broker is spawned `detached` + `unref`'d and has no timer of any kind — no idle bound, no orphan check — so the only thing that can stop it is the SessionEnd hook calling `releaseBrokerOwner(sessionId)`, which matches a broker only when its `broker.json` `owners` array contains the dying `CODEX_COMPANION_SESSION_ID`.

`owners` is populated exclusively from that environment variable. The documented suite command scrubs it (`env -u CODEX_COMPANION_SESSION_ID …`), so **every broker a test spawns is unowned and therefore unreapable**. Two further paths spawn brokers and then deliberately fail to kill them: `ensureBrokerSession`'s not-ready path and its stale-record path both pass `killProcess: null`, and `teardownBrokerSession` gates the kill on `Number.isFinite(pid) && killProcess` — so those paths delete the pid/log/socket files and leave the child running, now invisible to every reaper that exists. And the reuse gate is a 150 ms socket connect and nothing else, so any answering socket is reused regardless of which plugin build spawned it.

Falsifying evidence, captured on this machine at 2026-08-12 10:47 while writing this spec: `pgrep -f "app-server-broker.mjs serve" | wc -l` = **39**. All 39 were spawned between 10:46:02 and 10:47:03 from `…/scratchpad/upstream/plugins/codex/scripts/app-server-broker.mjs` — the Phase-0 verification clone — each with `--cwd` pointing at a `codex-plugin-test-*` temp workspace that no longer exists, and each still holding a live fake `codex app-server` child: **78 leaked node processes from one suite run**. The issue reports 514 accumulated over two days, which exhausted swap on this 16 GB machine.

This is the follow-up the issue #2 spec deferred: its Out-of-scope list names "Broker lifecycle changes (`broker-lifecycle.mjs`, app-server broker)".

## Intent

Give every broker a reaper, and give the broker itself a falsifiable reason to stop existing. Three mechanisms, each owning a distinct failure mode:

1. **The broker supervises itself** — it periodically re-reads the workspace's broker record and exits when the record no longer names it, or when nothing has connected to it for a bounded idle interval. This is the machine-level backstop that makes "immortal" impossible, whatever the caller did or failed to do.
2. **The suite reaps deterministically** — no test file writes under a state root it shares with anything else (most adopt one helper that pins a private root; the one file that already pins per test keeps its own arrangement), and every file that can spawn a broker stops every broker recorded under its root at file teardown, so a suite run leaves the process table exactly as it found it, immediately.
3. **The spawn paths stop lying** — a teardown that is asked to clean up after a broker actually kills it, and the reuse gate refuses a broker from a different plugin build.

Entirely inside the repo's `codex-plugin-cc` patch plus a `patchRevision` bump. No change to broker request routing or the app-server protocol.

## Terminology

The word "session" is already overloaded in this runtime and the overload is load-bearing here, so this spec fixes the vocabulary and new identifiers must follow it:

- **broker record** — the contents of `broker.json` for one workspace state dir. Exactly one per workspace. (The existing `loadBrokerSession`/`saveBrokerSession`/`clearBrokerSession` names are upstream API and stay; *new* names say "record", following the "job record" precedent from issue #2's spec.)
- **session** — a Claude Code session, identified by `CODEX_COMPANION_SESSION_ID`. This is what `owners` holds and the only thing SessionEnd can reap.
- **owner / ownership / adopt** — reserved for the session→broker relation above. The broker's own "I have seen a record naming me" latch is called **recorded**, never "adopted", so the two never blur.
- **broker session dir** — the `mkdtemp` directory holding one broker's socket, pid file and log file.

## Requirements (bound to acceptance criteria)

| # | Requirement | Acceptance criterion |
|---|---|---|
| R1 | A full suite run with the documented env-scrubbed command leaves zero additional `app-server-broker` processes and zero additional orphaned `codex app-server` processes, measured immediately after the run. | AC1 |
| R2 | The single-test repro (`--test-name-pattern 'shared broker'`) leaves zero additional brokers. | AC2 |
| R3 | A live broker whose broker record has been deleted, or replaced by a record naming a different endpoint, exits on its own within a bounded interval; so does a broker no client has connected to for the idle bound. Either exit leaves behind no socket, no pid file, no log file, no broker session dir, and no record naming a dead broker — and takes the broker's `codex app-server` child with it. | AC3 |
| R4 | `ensureBrokerSession`'s not-ready path terminates the child it just spawned, together with that child's own app-server child; so does its stale-record path. | AC4 |
| R5 | `ensureBrokerSession` does not reuse a broker recorded by a different plugin build; it retires that broker and spawns a fresh one. Records written before this change carry no build identity and are treated as foreign. | AC5 |
| R6 | `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs` passes in a patched checkout of the pinned revision, including new tests that fail at p5 for each of R3, R4, R5. | AC6 |
| R7 | `patches/agent-plugins/codex-plugin-cc.patch` is regenerated, `patchRevision` in `lib/agent-plugins.nix` is bumped 5→6, and `just build` succeeds. | AC6 |
| R8 | Once the suite is observed leaving the live plugin data dir clean, the one CLAUDE.md sentence claiming every test run leaks `codex-plugin-test-*` state dirs into it is corrected. | — (doc truth) |

## Design options considered

**A — Broker self-supervision + deterministic suite reaping + honest teardown (chosen).** Three mechanisms, three failure modes, no overlap. AC3 asks for self-termination "within a bounded interval"; AC1 asks for `pgrep` to be unchanged *immediately* after a suite run. No single mechanism satisfies both — a timer cannot be immediate, and a suite hook cannot bound a broker whose owning process was killed. So the answer to "self-termination, suite teardown, or both" is settled by the acceptance criteria themselves.

**B — Ownership for test runs only** (pin a synthetic `CODEX_COMPANION_SESSION_ID` per test file and let the existing `releaseBrokerOwner` path reap). Rejected as the *primary* mechanism: it fixes only the tests, leaves every non-session broker (a plain-shell `codex-companion review`, a session whose SessionEnd hook never ran) immortal, and it re-introduces into the suite the exact variable the documented run command scrubs because 4 upstream tests fail spuriously when it is set. A per-file synthetic session id would also silently change what the session-filtered listing tests exercise.

**C — Broker-side idle timer alone.** Rejected: cannot satisfy AC1's "immediately". Also leaves the not-ready and stale paths leaking a broker for a full idle interval each time, and leaves a wrong-build broker serving requests until it happens to go idle.

**D — Owner-liveness probe: record the spawning process's pid as an owner and exit when all owners are dead.** Tempting because it mirrors issue #2's driver-pid probe, and it makes orphan detection decidable without a Claude session. Rejected: the spawning CLI process is short-lived by design, so a pid owner is dead seconds after every command and the broker would never be shared at all — it would delete the feature the broker exists to provide. The idle bound gives non-session callers a bounded sharing window instead, which is strictly better than both extremes.

**E — A sweeper/GC process that reaps brokers workspace-wide.** Rejected on the same grounds the issue #2 spec rejected it: a process with no live caller contradicts the Node standard's "background work that must continue with no live caller is a separate process, not an import" *and* adds a second daemon to supervise. The broker is already a separate process; it can supervise itself.

## Decisions

### D-1 · Broker self-supervision: what "no longer wanted" means

The broker gains a periodic supervision tick. It can do this because it already receives `--cwd` and inherits `CLAUDE_PLUGIN_DATA` through `createWorkspaceRuntime`'s env, so it can resolve and read the same broker record its spawner wrote.

Identity: **a broker record is "mine" iff `record.endpoint` equals the endpoint this broker was started with.** Endpoints are unique per broker (each is a socket inside a fresh `mkdtemp` broker session dir), so no new field is needed to answer "does the record still name me".

The tick classifies the record as `mine`, `foreign`, `missing`, or `unreadable`, and the decision is taken in this order:

1. **`foreign`** → exit. A different broker owns this workspace now; this one is unreachable by design. Exit even if a client is connected: whoever replaced the record already decided this broker is gone.
2. **`missing` and this broker is `recorded`** → exit. The `recorded` latch flips true the first tick the record is `mine`. Before that, a missing record is the expected state — `ensureBrokerSession` writes the record only *after* `waitForBrokerEndpoint` succeeds, so a young broker is legitimately unrecorded. The latch replaces what would otherwise be an arbitrary grace window.
3. **No connection open, and none for the idle bound** → exit. This is the one criterion that covers every un-ownable case at once: unowned test brokers, plain-shell CLI brokers, and brokers whose owning session died without its SessionEnd hook running.
4. **`unreadable`** (the record exists but does not parse) → continue. Only a definite absence justifies an exit, exactly as issue #2 settled that only `ESRCH` proves a process is absent. Records are written by atomic rename, so a parse failure is real corruption, not a torn read — and killing a live broker over it would be the aggressive, irreversible direction.

**An empty `owners` array is not orphanhood.** `owners: []` is the normal, correct steady state for every non-session caller; treating it as orphaned would kill a broker that a plain-shell `codex-companion review` is about to reuse. Ownership stays what it is today — the set of Claude sessions that have adopted this broker, and the input to SessionEnd reaping — and the idle bound is what bounds unowned brokers. Consequently "a broker whose owners are all gone" (AC3's phrasing) is satisfied on two paths: when SessionEnd runs, the existing `releaseBrokerOwner` deletes the record and shuts the broker down; when it does not run, session ids are not probeable for liveness, so the idle bound is the bound.

**Idle definition.** Idle time is time with zero connected sockets; that is the whole rule, because an in-flight request or stream implies a connected socket — verified: the broker's `clearSocketOwnership` runs on both socket `close` and socket `error` and nulls `activeRequestSocket` and `activeStreamSocket`, so the two can never outlive the socket set. The clock starts at broker startup and is refreshed on every connection, every inbound line, and every socket close. Note that `waitForBrokerEndpoint` and `isBrokerEndpointReady` both connect-and-close, so a readiness probe refreshes the clock — which closes the only interesting race: a probe that reports the broker ready cannot be followed by an idle exit for a full idle interval.

**Bounds.** Idle bound defaults to 10 minutes; the supervision tick to 15 seconds. Both are overridable by environment variable (D-4). Ten minutes is comfortably longer than any single bounded call in this runtime (the bridge's 540 s wait chunks, the reviewer's 840 s internal timeout — during which a socket is connected, so the idle clock is not even running), and short enough that an abandoned workspace releases its runtime within a coffee break. The harm is asymmetric and both directions are cheap: too short costs one `codex app-server` restart; too long costs one idle node pair. Neither can fabricate a failure, which is why a wall-clock bound is acceptable here and was not acceptable for issue #2's job-state heuristic — that one would have flipped a live job to `failed`.

**Exit sequence.** In order:

1. Write one line naming the exit reason to the broker log. It is the only debugger for a process nobody is attached to, and it is what makes a future "why did my broker vanish?" answerable.
2. Under the workspace's broker metadata lock, delete the broker record **iff it is still mine**. Never on the `foreign` path — that record belongs to the new broker.
3. Run the broker's `shutdown(server)`, extended to leave nothing behind: it already closes client sockets, closes the app-server client (which stops the `codex app-server` child), closes the listener, and unlinks the socket and pid file. It gains the log file (see D-6's `--log-file`) and then a non-recursive `rmdir` of the broker session dir, in a try/catch — if anything unexpected is in that directory, it stays.
4. `process.exit(0)`. A self-reap is not a failure.

**Lock contention during self-exit.** `ensureBrokerSession` holds the broker metadata lock for its whole body, so a supervision tick can time out acquiring it. That is not a fault: log the contention and retry on the next tick. This is a periodic task retrying, not an error being muted — and the alternative (an unhandled rejection killing the broker) would leave the record naming a dead process, which is the lie this design removes.

**Placement.** The decision is a pure function in a new `lib/broker-supervisor.mjs` — it takes the classified record, the `recorded` latch, the connection count, the clocks and the bounds, and returns continue-or-exit-with-reason. It owns no timers, touches no processes, and is therefore unit-testable without a stopwatch. `app-server-broker.mjs` owns the wiring: resolve the record path **once** at startup (`resolveWorkspaceRoot` shells out to `git rev-parse`, so per-tick resolution would be both wasteful and non-deterministic if the workspace's git state changed), start an `unref`'d interval inside `main()` (never at import — the Node standard forbids a module that starts a timer when imported), and guard re-entrancy with an exiting flag so overlapping ticks cannot double-shutdown. Sibling-module precedent: `broker-endpoint.mjs` is already a flat policy module beside `broker-lifecycle.mjs`.

### D-2 · Build identity in the reuse gate

The broker record gains **`scriptPath`** — the absolute path of the `app-server-broker.mjs` that spawned this broker, which `ensureBrokerSession` already resolves. `ensureBrokerSession` reuses an existing record iff `existing.scriptPath` equals the script path it is about to use **and** the endpoint answers; the build check is free, so it runs before the 150 ms socket probe. The script-path resolution therefore moves above the reuse check.

Under a Nix-managed install this path is a store path whose hash covers the whole patched tree and whose name embeds the build version — verified: `installed_plugins.json` records `installPath = /nix/store/b4p6s8fmnk1sb074wjly85z3v2cbd2ga-codex-plugin-cc-1.0.6-nix.db52e28f.p5/plugins/codex`, and `lib/agent-plugins.nix` names the derivation `codex-plugin-cc-${codexVersion}` where `codexVersion` embeds `p${patchRevision}`. So the path changes whenever the patch or the patch revision changes, which is exactly the identity AC5 asks for. It is also better diagnostics than an opaque id: reading the broker record tells you which build is serving a workspace, which is how the p3-under-p5 observation in the issue was made in the first place.

A record written by any earlier build has no `scriptPath` at all, so `undefined !== path` retires it on first contact. No migration code.

**Consequence that must be stated, not discovered: retiring a foreign-build broker can interrupt work it is currently serving.** There is exactly one broker record per workspace, so a new build cannot spawn alongside an old broker — writing the new record would make the old broker `foreign`, and it would self-exit anyway. Killing it in the same breath is therefore not an extra cost, it is the same outcome sooner and with the files cleaned up. In the worst case a background task worker from an older build loses its app-server mid-turn and its job fails; that job's failure is truthful (its runtime is gone) and issue #2's dead-worker healing already reports it. The alternative — leave the old broker running and unrecorded — recreates precisely the immortal-broker class this issue exists to close.

**The stop is a group SIGTERM, not a `broker/shutdown` round-trip.** `releaseBrokerOwner` sends `broker/shutdown` before tearing down, but `sendBrokerShutdown` resolves only on data, error or close and carries **no timeout**, so awaiting it inside `ensureBrokerSession` — which holds the workspace broker lock for its whole body — would let one wedged broker hang every future companion command in that workspace. SIGTERM reaches the same place: the broker's own `SIGTERM` handler runs the same `shutdown(server)` sequence the `broker/shutdown` request runs. So the graceful path is preserved without the unbounded wait.

### D-3 · Deterministic suite reaping, scoped so it can never reap a real broker

The lever is process-per-file isolation plus the fact that `buildEnv(binDir)` spreads `process.env` wholesale, so anything a test file pins at module scope reaches every spawned CLI child and, through `createWorkspaceRuntime`'s env, every broker.

`tests/helpers.mjs` — the existing home for `makeTempDir`/`run`/`initGitRepo` — gains one function that a test file calls once at module scope. It:

- pins `CLAUDE_PLUGIN_DATA` to a fresh temp dir, so `resolveStateRoot()` for this file (and every child it spawns) is a private tree that contains only this file's state, and
- registers a `node:test` file-scoped `after` hook that walks the broker records under that root and stops each one: **group** SIGTERM via `terminateProcessTree`, then a bounded poll on `isProcessAlive`, then a **group** SIGKILL (`-pid`, falling back to `pid`), then remove the record, socket, pid file, log file and broker session dir.

The kill must be group-wide at both stages, because each broker holds a `codex app-server` child: a `pid`-only SIGKILL would satisfy `pgrep -f app-server-broker` while stranding 39 app-servers, which is why R1 counts both.

Two properties matter. First, the reaper is **scoped by construction** — because the root is a private temp dir, it is impossible for it to touch a developer's own broker, which is what rules out the "walk the shared state root and kill everything" variant (under the documented scrubbed command the shared root is `os.tmpdir()/codex-companion`, where a real plain-shell broker lives). The hook re-pins the captured root into `CLAUDE_PLUGIN_DATA` before walking, so a test that temporarily repointed it (the `isolation.test.mjs` pattern) cannot send the reaper to the wrong root. Second, it is **verified, not hopeful** — the escalation to SIGKILL after a bounded wait is what makes AC1's "immediately" true even if a broker's graceful shutdown wedges.

**Which files adopt it: every test file that writes under the state root** — a rule that needs no inventory of which *commands* happen to connect to a broker, a fact that rots (`setup` reaches a broker through its auth-status check, which the command name does not suggest). Verified by grep, those files are `runtime.test.mjs` and `state.test.mjs` (neither pins anything today), and `liveness.test.mjs` and `reviewer-detach.test.mjs` (which hand-roll the pin and adopt the helper instead), plus the new test file. `isolation.test.mjs` already pins and restores per test and is left alone. `commands.test.mjs`, `git.test.mjs`, `render.test.mjs`, `process.test.mjs`, `broker-endpoint.test.mjs` and `bump-version.test.mjs` never touch the state root. The one test that overrides `CLAUDE_PLUGIN_DATA` per child — the SessionStart env-file test — spawns no broker, so nothing escapes the pinned root.

Including `state.test.mjs` is what makes R8 fully true rather than half true: it writes state dirs through `saveState`/`listJobs` without ever spawning a broker, so it is the remaining source of `codex-plugin-test-*` dirs in the live plugin data dir. Its two existing assertions survive the pin — `resolveStateDir` still starts with `os.tmpdir()` because `makeTempDir` lives there, and its second test's save/restore of `CLAUDE_PLUGIN_DATA` restores the pinned value.

**Constraint the plan inherits:** no test may leave a background task worker running past the end of its file, because the reaper would pull the broker out from under it. Every existing `--background` test already waits for a terminal job state before returning; new tests must too.

### D-4 · Supervision bounds are configured by environment variable

Two constants, exported from `lib/broker-supervisor.mjs` and read once at broker startup: an idle-bound variable (default 10 minutes) and a supervision-interval variable (default 15 seconds). An environment variable is the only seam that reaches the broker without threading a test-only value through `spawnBrokerProcess`, and it works from all three directions a test needs — a direct `spawnBrokerProcess` call, an `ensureBrokerSession({ env })` call, and an end-to-end CLI run whose env spreads through `buildEnv`. It is also the runtime's established cross-process configuration idiom (`CLAUDE_PLUGIN_DATA`, `CODEX_COMPANION_APP_SERVER_ENDPOINT`, `CODEX_COMPANION_CANONICAL_CODEX_HOME`).

Parsing is strict: a positive integer, or the broker throws at startup. A bad value must not silently fall back to the default — it would produce a broker whose reaping behavior nobody can predict. Throwing is loud in exactly the right way: the broker never becomes ready, `ensureBrokerSession` returns null, and the CLI reports that it failed to start the broker.

Production never sets either variable. They exist so the two self-termination behaviors have tests that can fail in seconds rather than in ten minutes. The corollary is stated plainly because it bounds what the suite proves: **the tests pin the mechanism at a configured bound; they do not assert the 10-minute and 15-second defaults**, because a test that waited for either would be a ten-minute test or a flaky stopwatch. The defaults are a reviewed constant, not a tested one.

### D-5 · Teardown kills by default, and tolerates racing itself

`teardownBrokerSession`'s `killProcess` parameter defaults to `terminateProcessTree` instead of `null`, and the three call sites inside `broker-lifecycle.mjs` stop passing `?? null` — omitting the option now means "use the default", not "do not kill". This is one authoritative home for the policy, and it makes the failure mode that caused this bug unreachable by omission. The parameter itself stays, as the injection seam it was meant to be. `session-lifecycle-hook.mjs` keeps its explicit pass: it is now redundant with the default but it is not a second home for the policy, and touching it would widen the patch for no behavior change.

`terminateProcessTree` is the right instrument precisely because it SIGTERMs the process **group** first. The not-ready path is the case that proves it: a broker that never became ready is usually still inside `CodexAppServerClient.connect`, and its SIGTERM/SIGINT handlers are installed only *after* that call returns — so it dies on the default SIGTERM disposition with no cleanup at all, and only a group signal also reaps the `codex app-server` it had already spawned. `child.kill()` would have left that grandchild orphaned and unfindable.

Consequence that must be handled in the same change: **the kill now races the broker's own shutdown**. A SIGTERM'd broker that *did* reach its handler unlinks its own socket, pid file and (per D-6) log file while `teardownBrokerSession` is unlinking the same paths, and today those removals are guarded by `existsSync` alone — a check-then-unlink with a window in between, which will throw `ENOENT` intermittently. Teardown's *file* removals therefore become force-removals. The broker session dir removal stays a non-recursive `rmdir` in a try/catch, exactly as today: "remove the directory if it is empty" is the correct, conservative post-condition, and a recursive force-delete of a path derived from a caller-supplied argument is not a trade this issue needs to make.

This race already exists latently on the `releaseBrokerOwner` path (it sends a shutdown, then tears down); fixing the kill turns a latent flake into a routine one, so the fix ships together.

`spawnBrokerProcess` keeps `detached: true` and `child.unref()`. Outliving the spawning CLI process is the broker's entire purpose; what was missing was not detachment but supervision.

### D-6 · The broker learns where its log file is

The broker is told its pid file (`--pid-file`) so it can unlink it on shutdown, but not its log file — so today every broker shutdown leaves `broker.log` and, because that file keeps the directory non-empty, the whole `cxc-*` broker session dir behind. R3 is unsatisfiable without fixing this, and the fix is the one the existing argument already models: `spawnBrokerProcess` passes `--log-file` alongside `--pid-file`, the broker adds it to its `valueOptions`, and its `shutdown` unlinks it before the non-recursive `rmdir`.

Unlinking a file that is still the process's own stdout/stderr is fine on POSIX (writes continue to the unlinked inode). On Windows it will fail, the try/catch absorbs it, and the directory simply stays — the same outcome `teardownBrokerSession` already produces there. The dead `LOG_FILE_ENV` export in `broker-lifecycle.mjs` is evidence upstream intended the broker to know this path; this delivers that intent through the flag that matches `--pid-file`, and the dead export is left alone (out of scope).

### D-7 · What deliberately does not change

`getSessionRuntimeStatus` keeps its current logic: it reports "shared session" whenever a broker record exists, without checking build identity or liveness. It is a cosmetic label on the `setup`/`status` report, an upstream test pins its behavior against a hand-seeded endpoint-only record, and no acceptance criterion touches it. It *will* start truthfully reporting "direct startup" after a self-exit, because the exiting broker deletes its own record — that is the label becoming more accurate, not a logic change.

`addOwner` keeps returning the session unchanged when no session id is present. That behavior is correct under this design (an unowned broker is a legitimate state, now bounded by the idle timer), and the issue's framing of it as the first defect misidentifies the root cause: the defect was never that `owners` stays empty, it was that ownership was the *only* reaping mechanism. The one refinement is that the record shape is normalized to always carry an `owners` array, so the supervisor and the reuse gate see one record contract.

### Module surface

- **`lib/broker-supervisor.mjs`** (new) — the record classification vocabulary, the two env-var names and their defaults, the strict bound parser, and the pure continue-or-exit decision.
- **`app-server-broker.mjs`** — accepts `--log-file`; resolves its record path once; tracks connection count and last-activity; latches `recorded`; runs the `unref`'d supervision interval inside `main()`; performs the exit sequence; extends `shutdown` to unlink the log file and `rmdir` the broker session dir.
- **`lib/broker-lifecycle.mjs`** — records and gates on `scriptPath`; passes `--log-file` in `spawnBrokerProcess`; exports a lock-guarded "delete the record iff it names this endpoint" for the broker's exit path; `teardownBrokerSession` defaults `killProcess` and force-removes files; imports `terminateProcessTree` from `lib/process.mjs` (no cycle — that module imports only node builtins).
- **`tests/helpers.mjs`** — the hermetic-state-root-plus-reaper helper.

Names are indicative; the plan may adjust identifiers, not responsibilities.

## Test seams

Agreed seams. The plan and every implementer inherit these and may not invent others.

1. **The supervision policy function** (`lib/broker-supervisor.mjs`) — called directly with fabricated inputs. No timers, no processes, no sleeps. This is where the decision table is pinned.
2. **The `broker-lifecycle.mjs` module API** — `ensureBrokerSession` with injected `scriptPath`, `env`, `timeoutMs` and `createBrokerEndpoint`, and `teardownBrokerSession` called directly. All four injection points exist at p5. Prior art: `tests/broker-endpoint.test.mjs` (module-level), and the seeded-record tests in `runtime.test.mjs`.
3. **A real spawned broker plus process liveness** — `spawnBrokerProcess` with the fake codex on PATH, asserting the process exits (bounded poll on `isProcessAlive`) and its files are gone. Prior art: `tests/liveness.test.mjs`'s detached sleeper processes with `t.after` teardown.
4. **The companion CLI subprocess surface** — `node scripts/codex-companion.mjs review|task …` against a temp workspace with the fake codex installed, plus the on-disk broker record read through the exported resolvers. Prior art: the `shared broker` test in `runtime.test.mjs`, `tests/isolation.test.mjs`.

Fixtures follow existing conventions: `makeTempDir` workspaces, `initGitRepo`, `installFakeCodex`, production-shaped broker records (full field set, not the shortest thing that parses), real detached processes for live/dead pids. No call-count assertions and no spy on `killProcess` anywhere — a killed process is observable, so observe it.

## Test strategy

One new behavior-named file, `tests/broker-reaping.test.mjs` (precedent: the patch already owns `tests/isolation.test.mjs`, `tests/liveness.test.mjs`, `tests/reviewer-detach.test.mjs`; `runtime.test.mjs` is not grown further).

1. **Supervision decision table** (seam 1, R3): continue while the record is mine and a client is connected; exit-replaced on a foreign record; exit-orphaned on a missing record once `recorded`; **continue** on a missing record before `recorded`; **continue** on an unreadable record; exit-idle at exactly the bound with zero connections; continue below the bound. Each row fails for exactly one reason.
2. **A live broker exits when its record disappears** (seam 3, R3): spawn a real broker with a short supervision interval, write its record, wait for readiness, delete the record; assert the process is gone, its `codex app-server` child is gone, and no socket, pid file, log file or broker session dir remains.
3. **A live broker exits when its record is replaced** (seam 3, R3): same setup, then overwrite the record with one naming a different endpoint; assert the process is gone **and the replacement record survives** — an exiting broker must never delete a record that is not its own.
4. **A live broker exits when nothing connects** (seam 3, R3): spawn with a tiny idle bound and never connect; assert the process is gone and the record it was given no longer exists.
5. **Teardown kills by default** (seam 2, R4): a live detached sleeper's pid passed to `teardownBrokerSession` with no `killProcess` argument dies. This is the direct regression guard on the `killProcess: null` root cause, and it fails at p5.
6. **The not-ready path terminates its child** (seam 2, R4): `ensureBrokerSession` with an injected broker script that records its own pid to a path given in the injected env, spawns a long-lived child of its own, and never listens, plus a short `timeoutMs`; assert the call returns null and that **both** recorded pids are dead — the group kill is the behavior under test. The pids come from the processes themselves, so nothing is mocked.
7. **The stale-record path terminates the broker it replaces** (seam 2, R4): seed a record whose endpoint does not answer and whose pid is a live sleeper; assert the sleeper is dead after `ensureBrokerSession`.
8. **A foreign-build broker is retired, not reused** (seam 2, R5): seed a record with a *ready* endpoint (a stub listener that records its pid) and a `scriptPath` from a different build; `ensureBrokerSession` returns a session with a different endpoint and the new `scriptPath`, and the stub's pid is dead. Positive control in the same file: a record with a matching `scriptPath` and a ready endpoint is reused — same endpoint returned, stub still alive. Without the control, test 8 passes trivially if reuse breaks entirely.
9. **The suite reaper actually reaps** (seam 4, R1/R2 mechanism): under the hermetic pin, run `codex-companion review` through the CLI with the fake codex, read the broker pid from the record, invoke the reaper, assert the pid and its app-server child are dead and the record is gone.

R1 and R2 are properties of a suite run, not assertions inside one; they are verified by the demo below. The 10-minute and 15-second defaults are reviewed, not tested (D-4). Existing coverage that must stay green and is not duplicated: the `shared broker` test in `runtime.test.mjs` (broker reuse across two CLI invocations still works — the build-identity gate must not break it, and both invocations resolve the same `scriptPath`, so it must not), the seeded endpoint-only record test that pins `getSessionRuntimeStatus`, and the whole of `tests/liveness.test.mjs`.

## Verification loop (for the plan to turn into tasks)

The nix-store plugin copy is read-only; all edits happen in a scratch clone of the pinned upstream and land in the repo only as a regenerated patch.

```sh
WORKTREE=<absolute path to this repo worktree>
scratch=$(mktemp -d)
gh repo clone openai/codex-plugin-cc "$scratch"
git -C "$scratch" checkout db52e28f4d9ded852ab3942cea316258ae4ef346
git -C "$scratch" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"   # zero-context patch; plain apply rejects it
git -C "$scratch" add -N .        # intent-to-add so patch-created files appear in git diff

# edit loop (the env scrub is mandatory: 4 upstream tests fail spuriously under a live
# Claude session env):
(cd "$scratch" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs)

# regenerate (re-run `git add -N .` first if new files were created, e.g. tests/broker-reaping.test.mjs):
git -C "$scratch" diff -U0 db52e28f4d9ded852ab3942cea316258ae4ef346 > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"

# bump patchRevision 5 -> 6 in lib/agent-plugins.nix, then:
just build
```

**Demo (AC1, AC2).** The before-count on this machine is **not** 0 — 39 leaked brokers from the Phase-0 verification run were alive when this spec was written — so the demo records the real before-count instead of assuming one, and reaps the pre-existing leak first so the numbers mean something. Both process families are counted, because a broker reaped without its process group leaves its app-server behind:

```sh
count() { printf 'brokers=%s app-servers=%s\n' \
  "$(pgrep -f 'app-server-broker.mjs serve' | wc -l | tr -d ' ')" \
  "$(pgrep -f 'codex app-server' | wc -l | tr -d ' ')"; }

count                                   # before
(cd "$scratch" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs)
count                                   # must equal before

(cd "$scratch" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
   node --test --test-name-pattern 'shared broker' tests/*.test.mjs)
count                                   # must still equal before
```

`just build` is the repo's only verification gate. R8's CLAUDE.md sentence is corrected only after the suite has been observed leaving no `codex-plugin-test-*` state dirs in the live plugin data dir — the doc change follows the evidence, it does not precede it.

## Out of scope

- The job-record heal-on-read machinery from issue #2 (`tracked-jobs.mjs`, `job-control.mjs`, the status surface) — untouched.
- Broker request routing, queueing, stream ownership and the app-server protocol.
- `getSessionRuntimeStatus`'s "shared session" label logic (D-7).
- `addOwner`'s no-session behavior and any change to what `owners` means (D-7).
- `sendBrokerShutdown`'s missing timeout, and the `releaseBrokerOwner` path that awaits it (D-2 avoids depending on it rather than fixing it).
- The dead `PID_FILE_ENV`/`LOG_FILE_ENV` exports (D-6 delivers the intent via a flag; the exports stay).
- The 4 upstream tests that fail spuriously under an unscrubbed live-session env; the documented scrub command stays authoritative.
- Any CLAUDE.md change beyond R8's single-sentence correction.
- A sweeper, GC daemon, or any reaping process with no live caller.
- Probing Claude session-id liveness (no mechanism exists; the idle bound is the substitute).
- Contributing the change upstream.

## Auto-resolved decisions

### Self-termination, suite teardown, or both
- **Question:** Does the suite get deterministic teardown, broker-side self-termination, or both?
- **Choice:** Both, with distinct jobs: broker self-supervision is the machine-level bound (AC3), the per-file suite reaper is the immediate one (AC1, AC2).
- **Grounding:** The acceptance criteria are mutually exclusive for any single mechanism. AC3 says a broker "exits on its own within a bounded interval"; AC1 says a full suite run leaves zero additional brokers, and the issue's demo measures `pgrep` immediately before and after. A timer cannot be immediate; a suite hook cannot bound a broker whose owner was killed. The issue's own fix-direction sentence permits "a combination".
- **Alternative considered:** Suite teardown alone (leaves every non-test broker immortal — the 514-broker report was not only tests) and a timer alone (cannot satisfy AC1). Both rejected.

### Does an empty `owners` array mean orphaned?
- **Question:** What bounded interval counts as "orphaned long enough to exit", and does `owners: []` count as orphaned or as not-yet-adopted?
- **Choice:** `owners: []` is **not** orphanhood — it is the legitimate steady state of every non-session caller. Orphanhood is decided by the record reference (record missing once `recorded`, or naming a different endpoint), and everything else is bounded by idle time, defaulting to 10 minutes.
- **Grounding:** The tension is called out in the issue itself: "`owners: []` is also the normal state for legitimate non-session CLI use, so an aggressive empty-owners exit could kill a broker a plain-shell `codex-companion review` is about to use." The-bar "Root causes" warns against building a mechanism around symptom-shaped evidence — an empty array is a symptom of "no Claude session", not of abandonment. Idle time is the falsifiable criterion, and unlike issue #2's rejected `updatedAt` heuristic it cannot fabricate a failure: the worst case is one `codex app-server` restart.
- **Alternative considered:** Exit when `owners` is empty for N seconds — rejected; it kills legitimate plain-shell brokers and makes the reaping policy depend on whether a Claude session happened to be present at spawn time.

### Build identity for the reuse gate
- **Question:** Is the broker's build identity the Nix store `scriptPath`, the plugin manifest version, or both?
- **Choice:** The resolved broker `scriptPath`, recorded in the broker record and compared for exact equality.
- **Grounding:** Verified that `installed_plugins.json` records `installPath = /nix/store/b4p6s8fmnk1sb074wjly85z3v2cbd2ga-codex-plugin-cc-1.0.6-nix.db52e28f.p5/plugins/codex` and that `lib/agent-plugins.nix` builds the derivation as `codex-plugin-cc-${codexVersion}` with `codexVersion` embedding `p${patchRevision}` — so the store path is a hash over the whole patched tree *and* changes on every patch-revision bump. It costs no IO (`ensureBrokerSession` already resolves it), it doubles as diagnostics in the record, and older records lacking the field are retired automatically.
- **Alternative considered:** The manifest version from `plugins/codex/.claude-plugin/plugin.json` — rejected as strictly worse on both ends: under Nix it is redundant (the store path already changed), and in a scratch clone it is the unrewritten upstream `1.0.6` for every patch revision, so it distinguishes nothing where a developer needs it most. Both together — rejected as two homes for one identity with no case that needs the second.

### Where the not-ready path's kill comes from
- **Question:** Should the not-ready path default `killProcess` to `terminateProcessTree`, or kill the just-spawned `child` handle directly?
- **Choice:** Default the parameter — `teardownBrokerSession({ killProcess = terminateProcessTree })` — and drop `?? null` at the three internal call sites.
- **Grounding:** DRY: one authoritative home for the policy, which every teardown path inherits, instead of one correct call site and two that still pass `null` (the stale path has the identical bug). `session-lifecycle-hook.mjs` already treats `terminateProcessTree` as the production kill, so the default matches established behavior rather than inventing it. And the group signal is required, not merely nicer: a not-ready broker is typically still inside `CodexAppServerClient.connect`, before its SIGTERM handler is installed, so it dies with no cleanup and only a group signal also reaps the `codex app-server` it already spawned.
- **Alternative considered:** `child.kill()` on the handle — rejected: it orphans the app-server grandchild and it fixes only the not-ready path, leaving the stale path leaking. Also considered removing the `killProcess` truthiness from teardown's kill condition — rejected as no-benefit churn once no caller can pass `null` by omission.

### Force-removal in teardown
- **Question:** Do teardown's file removals need to tolerate `ENOENT` now that it actually kills?
- **Choice:** Yes for the pid, log and socket files. The broker session dir stays a non-recursive `rmdir` in a try/catch.
- **Grounding:** A SIGTERM'd broker runs its own `shutdown`, which unlinks the socket, pid and log files, concurrently with teardown unlinking the same paths behind an `existsSync` check — a check-then-act with a real window. The-bar "Root causes" forbids papering over a race, but this is not papering: the correct post-condition is "the file is absent", and a force-removal states exactly that. The directory keeps the conservative rule because "remove it if it is empty" is the true post-condition there, and a recursive force-delete of a caller-supplied path is a risk this issue does not need to take.
- **Alternative considered:** Leave the removals as-is and accept intermittent throws — rejected; it would make the new tests flaky and the failure would surface as a mysterious `ENOENT` during session end.

### Where the supervision decision lives
- **Question:** Should the orphan/idle decision be inline in `app-server-broker.mjs` or a separate module?
- **Choice:** A pure decision function in a new `lib/broker-supervisor.mjs`; `app-server-broker.mjs` owns only the timer, the counters and the exit sequence.
- **Grounding:** the-bar "Tests that can fail" — a pure function gives the decision table a test that fails for exactly one reason and needs no sleeps, which is the difference between seven fast unit rows and seven multi-second process tests. Single responsibility along the existing boundary: `broker-endpoint.mjs` is already a flat policy module beside `broker-lifecycle.mjs`, so this follows the layout rather than inventing one. The Node shard's "no side effects at import" is satisfied because the module exports a function and starts nothing.
- **Alternative considered:** Inline in the broker with only integration coverage — rejected; every decision row would cost a spawned process and a wall-clock wait, and the decision table is exactly the part that must be unambiguous.

### How tests shorten the bounds
- **Question:** How do tests exercise idle and orphan exits without waiting ten minutes — CLI flags on the broker, or environment variables?
- **Choice:** Two environment variables (idle bound, supervision interval), read once at broker startup, strictly parsed, defaulting to 10 minutes and 15 seconds. Production sets neither.
- **Grounding:** Env is the only seam that reaches the broker from all three directions a test needs — a direct `spawnBrokerProcess`, an `ensureBrokerSession({ env })`, and an end-to-end CLI run (verified: `buildEnv` spreads `process.env`, and `createWorkspaceRuntime` spreads it again into the broker's env). A flag would require `spawnBrokerProcess` to thread a test-only parameter through production code. Env config is the runtime's existing idiom (`CLAUDE_PLUGIN_DATA`, `CODEX_COMPANION_APP_SERVER_ENDPOINT`, `CODEX_COMPANION_CANONICAL_CODEX_HOME`).
- **Alternative considered:** `--idle-timeout-ms` / `--supervise-interval-ms` flags — rejected for the production plumbing and because a flag cannot be set by an end-to-end CLI test. Deriving the tick from the idle bound to avoid a second knob — rejected: it couples the orphan-exit test's latency to the idle bound, so one test would have to choose between being slow and firing the wrong exit reason. (`PID_FILE_ENV`/`LOG_FILE_ENV` were **not** cited as precedent: both are exported and dead.)

### Invalid bound values
- **Question:** If an override is not a positive integer, fall back to the default or fail?
- **Choice:** Throw at broker startup.
- **Grounding:** the-bar "Fail loud". A silent fallback yields a broker whose reaping behavior contradicts what the caller asked for, which is unobservable until it leaks. Throwing is contained and legible: the broker never becomes ready, `ensureBrokerSession` returns null, and the CLI already says it failed to start the broker.
- **Alternative considered:** Clamp or default silently — rejected; it hides a misconfiguration in exactly the mechanism whose job is to prevent invisible accumulation.

### `recorded` latch instead of a startup grace window
- **Question:** A young broker is legitimately unrecorded (the record is written only after readiness). How is that distinguished from an orphan?
- **Choice:** Exit on a missing record only after the broker has observed its own record at least once — a latch, not a time window.
- **Grounding:** Verified in `ensureBrokerSession`: the record is written after `waitForBrokerEndpoint` succeeds, so "missing" is the expected state during startup and for the whole not-ready path. A latch has a falsifiable boundary ("has it ever been named?"); a grace window would be an unfalsifiable magic number of exactly the kind issue #2's spec rejected. The never-recorded broker is not left running: the not-ready path now kills it (R4), and the idle bound catches anything that escapes.
- **Alternative considered:** A startup grace period before orphan checks begin — rejected as an untestable threshold that would also have to exceed the readiness timeout, coupling two unrelated bounds.

### An unreadable record does not kill the broker
- **Question:** Should a `broker.json` that fails to parse count as missing?
- **Choice:** No — continue running, and re-check on the next tick.
- **Grounding:** Direct symmetry with the settled precedent in `.claude/specs/2026-08-10-truthful-job-terminal-states-design.md`: "only ESRCH proves absence… a wrong 'alive' degrades to the pre-probe behavior, a wrong 'dead' would fabricate a failure." Records are written by atomic rename, so a parse failure is real corruption rather than a torn read, and killing a serving broker over it is the irreversible direction.
- **Alternative considered:** Treat unparseable as missing — rejected; it would let one corrupt byte kill a broker mid-turn.

### Lock timeout during self-exit
- **Question:** The broker needs the workspace broker lock to delete its own record, and `ensureBrokerSession` holds that lock for its whole body. What happens on a timeout?
- **Choice:** Log the contention and retry on the next tick.
- **Grounding:** This is a periodic task retrying, not a swallowed error: the operation is idempotent, the next tick is seconds away, and the condition (another process is mid-`ensureBrokerSession` on this workspace) is legitimate rather than faulty. The alternative — an unhandled rejection inside a timer — would kill the broker while leaving a record that names a dead process, which is precisely the untruthful state this design removes. The issue #2 spec's "lock timeout propagates" rule applies to a *read path a user is waiting on*, which this is not.
- **Alternative considered:** Propagate and let the broker die — rejected for the stale record it would leave behind.

### Broker identity for the record check
- **Question:** How does a broker recognize its own record — by pid, by endpoint, or by a new id field?
- **Choice:** By endpoint equality; no new field.
- **Grounding:** Each broker's endpoint is a socket inside a fresh `mkdtemp` broker session dir, so it is already unique per broker, and the broker receives it on its own command line. Adding an id would be a second identity for the same thing (DRY), and pid comparison would need the record's pid to be trustworthy on paths where it is `null`.
- **Alternative considered:** Compare the recorded pid to `process.pid` — rejected; the record legitimately carries `pid: null` when a spawn produced no pid, and endpoint uniqueness already decides the question.

### Scoping the suite reaper so it cannot kill a real broker
- **Question:** How does a test-suite reaper find "its" brokers without touching a developer's plain-shell broker in the shared state root?
- **Choice:** Every state-writing test file pins `CLAUDE_PLUGIN_DATA` to a fresh temp dir at module scope; the file-scoped `after` hook reaps only the broker records under that private root, re-pinning the captured root before it walks.
- **Grounding:** `resolveStateRoot()` is `$CLAUDE_PLUGIN_DATA/state` or else `os.tmpdir()/codex-companion` — under the documented scrubbed command the fallback is *shared with real brokers*, so an unscoped walk is dangerous. `tests/liveness.test.mjs` already establishes exactly this pin, with a comment explaining that `node --test` gives each file its own process; the Node shard states the same rule ("set the environment the module reads before the first import in that file"). `buildEnv` spreading `process.env` is what carries the pin to every child. Re-pinning before the walk is required because `listStateDirs()` resolves the root at call time and `isolation.test.mjs` shows tests do repoint it mid-file.
- **Alternative considered:** Walk the shared state root and reap everything (would kill a developer's live broker), and reap by pid pattern via `pgrep` (same problem, plus it is not portable to the Windows paths this suite still supports).

### Reaper escalates to SIGKILL, group-wide
- **Question:** Is SIGTERM enough for the suite reaper, given AC1 measures the process table immediately?
- **Choice:** Group SIGTERM via `terminateProcessTree`, then a bounded poll on `isProcessAlive`, then a group SIGKILL (`-pid`, falling back to `pid`).
- **Grounding:** the-bar "Verify before claiming done" — AC1 is a claim about the process table at a specific instant, so the reaper must confirm rather than assume. A broker's graceful shutdown awaits its `codex app-server` child's exit, which is a wedge risk the test harness should not inherit. The escalation must be group-wide or it strands one `codex app-server` per broker — the observed leak is 39 brokers *and* 39 app-servers, which is why R1 counts both families. Both primitives already exist in `lib/process.mjs`.
- **Alternative considered:** SIGTERM and hope — rejected; it makes AC1 probabilistic. A `pid`-only SIGKILL — rejected; it satisfies `pgrep -f app-server-broker` while leaving the real memory behind. Escalating in the *production* teardown too — rejected as scope creep: production has the idle timer as its backstop, and a hard kill there would skip the app-server's own shutdown.

### No short idle bound pinned by the test helper
- **Question:** Should the hermetic helper also pin a short idle bound so brokers self-reap if a test file crashes before its `after` hook runs?
- **Choice:** No. One mechanism per job: the reaper for the suite, the 10-minute default as the machine-level backstop.
- **Grounding:** YAGNI, and the scenario is self-defeating — a test file that crashes hard fails AC6 (suite green) before AC1 is even meaningful. Pinning a second bound would add a knob whose only effect is to introduce a new way for a future long-running test to be reaped mid-run.
- **Alternative considered:** Pin a 1–2 minute idle bound in the helper as defense in depth — rejected as a magic number guarding a case that already fails a different acceptance criterion.

### Which test files adopt the hermetic pin (grill round)
- **Question:** Apply the pin and reaper only to files whose commands are known to connect to a broker, or to every file that writes under the state root?
- **Choice:** Every file that writes under the state root: `runtime.test.mjs`, `state.test.mjs`, `liveness.test.mjs`, `reviewer-detach.test.mjs`, and the new `tests/broker-reaping.test.mjs`. `isolation.test.mjs` already pins and restores per test and is left alone.
- **Grounding:** The narrower "files that invoke the CLI" rule leaves R8 half-true: verified by grep that `state.test.mjs` imports `lib/state.mjs` and writes state dirs through `saveState`/`listJobs` without ever spawning a broker, so it would keep depositing `codex-plugin-test-*` dirs in the live plugin data dir and the CLAUDE.md sentence would still be partly right. The state-root rule also needs no inventory of which commands connect — a fact that rots, since `setup` reaches a broker through its auth-status check. Verified safe for `state.test.mjs`: its `os.tmpdir()` assertion still holds because `makeTempDir` lives there, and its own save/restore of the variable restores the pinned value.
- **Alternative considered:** Pin only the CLI-invoking files — rejected because it makes R8's doc correction untrue. Pin every test file — rejected as churn in six files that never touch the state root.

### Retiring a live foreign-build broker interrupts what it is serving (grill round)
- **Question:** AC5 says a foreign-build broker must not be *reused*. Must it also be killed, even mid-turn?
- **Choice:** Yes — kill it. And say so in the spec rather than letting an implementer discover it.
- **Grounding:** There is one broker record per workspace, so a new build cannot spawn alongside the old broker: writing the new record makes the old one `foreign`, and it self-exits on its next tick regardless. Killing it in the same breath is the same outcome sooner, with its files cleaned up, instead of an unrecorded broker in the window between. A background worker from the older build that loses its app-server fails truthfully, and issue #2's dead-worker healing already surfaces that. Leaving it alive and unrecorded would recreate exactly the immortal-broker class this issue closes.
- **Alternative considered:** Spawn the new broker alongside and let the old one drain — impossible without a second record per workspace, which is a schema change no acceptance criterion asks for.

### Stop a live foreign-build broker with SIGTERM, not `broker/shutdown` (grill round)
- **Question:** `releaseBrokerOwner` sends `broker/shutdown` before tearing a broker down. Should the build-mismatch path do the same for symmetry?
- **Choice:** No — group SIGTERM only.
- **Grounding:** `sendBrokerShutdown` resolves on data, error or close and carries **no timeout**; `ensureBrokerSession` holds the workspace broker lock for its whole body, so awaiting it there would let one wedged broker hang every future companion command in that workspace. SIGTERM reaches the same code: the broker's `SIGTERM` handler runs the same `shutdown(server)` the `broker/shutdown` request runs, so gracefulness is preserved without the unbounded wait.
- **Alternative considered:** Send `broker/shutdown` with a new timeout — rejected; fixing `sendBrokerShutdown`'s missing bound is a real defect but it belongs to the `releaseBrokerOwner` path, is not needed by any acceptance criterion here, and is recorded in Out of scope instead of being smuggled in.

### The broker must be told its log file (grill round)
- **Question:** R3 demands that a self-exit leave no log file and no broker session dir, but the broker is never told where its log file is. How is R3 satisfiable?
- **Choice:** `spawnBrokerProcess` passes `--log-file` beside the `--pid-file` it already passes; the broker adds it to `valueOptions` and unlinks it in `shutdown`, then `rmdir`s the broker session dir non-recursively.
- **Grounding:** `--pid-file` exists for precisely this reason — so the broker can remove its own artifact — so the flag follows an established local pattern rather than inventing one, and the dead `LOG_FILE_ENV` export is evidence upstream meant the broker to know this path. Without it, every self-exit leaves `broker.log` behind, which also keeps the `cxc-*` directory non-empty so the `rmdir` can never succeed: R3 would be unachievable, and the fix would look like it worked while quietly leaking a directory per broker lifetime.
- **Alternative considered:** Derive the broker session dir from the socket or pid path and `rmSync` it recursively with force — rejected as a recursive force-delete of a caller-supplied path for a problem an explicit argument solves exactly. Relaxing R3 to tolerate the leftover directory — rejected; "the leak is only bytes now" is how the original leak was tolerated.

### "Broker record" versus "broker session" (grill round)
- **Question:** The code calls the `broker.json` contents a "broker session", while `owners` holds Claude *session* ids and `CODEX_COMPANION_SESSION_ID` names a Claude session. Which sense of "session" does this spec use?
- **Choice:** Fix the vocabulary in a Terminology section: **broker record** for the file's contents, **session** only for a Claude session, **owner/adopt** only for the session→broker relation, and **`recorded`** (never "adopted") for the broker's own latch. Existing exported names keep their spelling; new identifiers follow the fixed vocabulary.
- **Grounding:** The grill pass caught the spec using "adopted" for both the `owners` relation and the broker's self-recognition latch in the same section — the exact overload that makes a design doc unimplementable. "Record" is the precedent from issue #2's spec, which says "job record" throughout for the same kind of on-disk state file. Renaming the exported `loadBrokerSession`/`saveBrokerSession` functions would widen the patch across every call site for a naming win, which the-bar's "moves keep their history" does not ask for here.
- **Alternative considered:** Rename the exported functions to `*BrokerRecord` — rejected as patch surface with no behavior change; keep the vocabulary discipline in new names only.

### The self-exit flips the session-runtime label (grill round)
- **Question:** D-7 says `getSessionRuntimeStatus` does not change. But a self-exit deletes the record, so `setup`/`status` will start reporting "direct startup" where it used to report "shared session". Is that a regression?
- **Choice:** No, and the spec now says so explicitly: the logic is unchanged, the label becomes truthful.
- **Grounding:** the-bar "Truthful terminal states": the label's own definition is "no shared Codex runtime is active yet… the first review or task command will start one on demand", which is exactly the state after a self-exit. Reporting "shared session" for a broker that no longer exists is the lie; the flip removes it. The upstream test that pins this label seeds its own record and never spawns a broker, so it is unaffected.
- **Alternative considered:** Have the broker leave its record behind on idle exit so the label stays "shared" — rejected; it would leave a record naming a dead process, which is the exact untruth this issue is about.

### Spec filename and location
- **Question:** Where does this design live?
- **Choice:** `.claude/specs/2026-08-12-broker-reaping-design.md`.
- **Grounding:** The repo's own convention, `YYYY-MM-DD-<topic>-design.md`, established by the eight existing files in `.claude/specs/`; the topic matches the worktree branch `worktree-issue-9-broker-reaping`. There is no `docs/` tree and no ADR convention in this repo, so the design decisions are recorded as decision sections here rather than in an invented `docs/adr/`.
- **Alternative considered:** Creating `docs/adr/` for D-1 and D-2 — rejected; inventing a convention for two decisions contradicts the brief and would leave a one-off tree nobody maintains.
