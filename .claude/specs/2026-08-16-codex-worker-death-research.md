# Why detached reviewer workers die mid-turn on oversized review inputs

**Durability: committed** (this file is committed with the work).

**Schema-version-1 evidence gate: not invoked.** Nothing in this report is a
live-availability or blocking claim (e.g. "the service is up now" / "this is
currently blocking X") — it is a historical forensic analysis of seven already-
terminal job records plus a forward recommendation. The `research-observations`
/ `agent-evidence` pipeline in the skill contract therefore does not apply, and
no standing conclusion is asserted through that mechanism. Confidence levels
below are stated in prose instead.

## Research question

Why do codex-companion detached reviewer workers die mid-model-turn without
recording a result, and why is that failure confined to oversized review
inputs?

## Bottom line (ranked verdict)

1. **Best-supported, but not directly proven: an external `SIGKILL`/`SIGTERM`
   delivered from outside the worker process itself**, with the origin
   undetermined between two candidates that are indistinguishable from the
   evidence available after the fact:
   - **(1a) OS-level memory-pressure kill** (macOS jetsam / kernel OOM). This
     has strong circumstantial support (a 16 GB machine, a well-documented,
     still-open upstream bug in the exact component involved) but **zero
     direct corroboration** in this machine's own logs — see "What I could not
     confirm" below. This is the weaker of the two once the log search is
     accounted for.
   - **(1b) The plugin's own broker self-reap / replacement logic**, which is
     source-verified (not hypothetical) to be capable of SIGTERM-ing a live
     broker's whole process group — including an in-flight app-server turn —
     and of self-cleaning so thoroughly that a successful firing leaves no
     artifact to find. This is mechanistically closer to the evidence (matches
     the exact "silent, traceless, mid-turn" signature) but I found no log
     that names it as the trigger for these specific seven deaths, and it is
     structurally ruled out for one of the three worktrees (issue-805, single
     attempt, no second job to trigger replacement).
   - I am **not able to discriminate between 1a and 1b with the evidence
     available**, and say so explicitly rather than picking one — see
     "Unfalsifiable with available evidence."
2. **Ruled out**: the worker's own in-process V8 heap OOM (no trace, and the
   plugin's own log-capture design would have caught it if it happened — see
   below).
3. **Ruled out**: `SessionEnd`-driven job cleanup killing the job directly (it
   stamps a different, distinguishable error message than the one observed).
4. **The common upstream trigger, regardless of which of 1a/1b pulls the
   trigger**: all seven failures, and none of the eight routinely-completing
   worktrees, are diffs that exceed this plugin's inline-diff cap and switch
   the review into a mode where the *model itself*, running inside the Rust
   `codex` app-server, fans out dozens of its own `git diff` tool calls. That
   app-server process is the exact component an existing, unfixed upstream
   issue (`openai/codex#24048`) documents as accumulating unbounded memory
   from large tool output before being killed.
5. **Bounding review-input size would very likely prevent these deaths**,
   independent of which kill mechanism is ultimately responsible: it removes
   the only condition all seven failures share and the eight successes lack.
   See "Actionable conclusion" for specifics.

---

## What I verified

### 1. The generic error message means an *external, unexplained* death, not a timeout or a known internal path

`Worker process ${probedPid} exited without recording a result.` is written by
`reconcileWorkerLiveness()` only when a job's own record is still
`queued`/`running`, `job.pid` is a finite number, and `process.kill(pid, 0)`
now reports the pid gone (`ESRCH`).
— `/nix/store/7yb2zd63hsqr8p0kg2jzd7rzj7yz2pc4-codex-plugin-cc-1.0.6-nix.db52e28f.p8/plugins/codex/scripts/lib/tracked-jobs.mjs:247-257`

`job.pid` is the pid of the **detached task-worker's own Node.js process**
(not the broker, not the app-server): `spawnDetachedTaskWorker()` spawns
`codex-companion.mjs task-worker ...` as a new child and records `child.pid`.
— `.../scripts/codex-companion.mjs:686-708`, `:754-765`

That spawn wrapper deliberately gives the worker child an `O_APPEND` fd on its
own job-log file specifically so an uncaught V8 "FATAL ERROR: Reached heap
limit" / abort trace — "which no catch can intercept" — would land in the log:
— `.../scripts/codex-companion.mjs:688-696` (comment, verbatim in source)

No such trace appears in any of the seven logs (verified directly, see §4).
Combined with the message's own precondition (pid confirmed dead via `kill(pid,
0)`, not merely unresponsive), this rules out (a) a worker-side timeout — that
path produces a distinct `Codex job timed out after ${timeoutMs}ms.` message
instead (`.../scripts/lib/codex.mjs:608-614`), consistent with the one clean
control case (`issue-1233`, `reviewer-msuzyh2c-jnmuvo`) — and (b) an in-process
V8 OOM abort of the worker itself.

### 2. `SessionEnd` cleanup is ruled out as the direct killer

`session-lifecycle-hook.mjs`'s `handleSessionEnd` → `cleanupSessionJobs()` does
call `terminateProcessTree(job.pid)` on any job still active when its owning
session ends — but it does so *inside the same synchronous write* that stamps
the record with `errorMessage: "Session ended while the job was still
${current.status}."`, a message distinct from the generic one.
— `.../scripts/job-control.mjs:42-110` (`terminalizeLiveSessionJob`), message
text at line 95.

None of the seven failed records carry that message; all seven carry the
generic "exited without recording a result" text (verified directly, §5). This
rules out `SessionEnd` cleanup as the direct kill path for these seven,
independent of whether the owning session had even ended yet (see §5 — it
hadn't).

### 3. Upstream `codex-cli` has a documented, unfixed, matching bug class

`openai/codex#24048` — "Codex app-server repeatedly killed by SIGKILL after
memory grows to ~27GB when handling large tool/log output" — filed 2026-05-22,
open, no linked fix PR, no maintainer response visible on the issue page.
Reporter's own diagnosis: OS-level OOM kill (not a V8 heap limit), from
unbounded accumulation of large tool/log output in the app-server's own
memory, with no cap or streaming/backpressure.
— https://github.com/openai/codex/issues/24048 (fetched directly)

`rust-v0.146.0` (released 2026-07-29T01:42Z) and `rust-v0.146.1` (released
2026-08-05T15:55Z) release notes, fetched directly, contain **no** fix
addressing app-server memory, worker/process death, or large-diff handling.
— https://github.com/openai/codex/releases/tag/rust-v0.146.0
— https://github.com/openai/codex/releases/tag/rust-v0.146.1

Both predate the entire death window (2026-08-10 through 2026-08-15), so
whichever of 0.146.x was active could not have carried a fix. **Correction to
the brief:** the currently-pinned/installed version is **not** 0.146.0 — `codex
--version` on this machine reports `codex-cli 0.147.0`
(`/etc/profiles/per-user/anis/bin/codex`), and `flake.lock`'s `codex-cli` input
was last advanced by commit `5fa03bb` ("chore: update flake inputs",
2026-08-15T20:50:11+01:00) — see §6 for why this specific update does not
change the broker-replacement analysis. `rust-v0.147.0` released
2026-08-07T01:41:49Z, also with no memory-handling fix in scope of what I
checked; I did not exhaustively review every 0.147.x/0.148.x-alpha changelog
line.

### 4. Source-verified mechanism for how a large diff reaches the app-server (not the worker)

Inline-diff thresholds: `DEFAULT_INLINE_DIFF_MAX_FILES = 2`,
`DEFAULT_INLINE_DIFF_MAX_BYTES = 256 * 1024`.
— `.../scripts/lib/git.mjs:8-9`

Above either threshold, the review switches to `inputMode: "self-collect"` and
the prompt sent to the model is: *"The repository context below is a
lightweight summary. Inspect the target diff yourself with read-only git
commands before finalizing findings."*
— `.../scripts/lib/git.mjs:297, 303-343`

This means the "dozens of `git diff --unified=25` calls across 44 files"
already observed in the `issue-1215` job log are executed by **the model,
inside the Rust `codex` app-server's own tool-calling turn** — not by the
companion's Node worker. The companion's own diff-size probe
(`measureGitOutputBytes`) is itself bounded (`maxBuffer: maxBytes + 1`,
`.../scripts/lib/git.mjs:40-41`), so the worker process does not balloon while
measuring. This is the load-bearing link between "oversized diff" and "the
process type (`openai/codex#24048`) documents as memory-unsafe under large
tool output" — the app-server, not the worker.

All three failing worktrees exceed both thresholds by a wide margin (9-44
files, 2,816-4,451 lines, vs. the 2-file/256KB cap); none of the eight
routinely-succeeding worktrees are reported to.

### 5. True death timestamps (not `completedAt`) and the shared-session fact

`completedAt`/`updatedAt` on a healed record is **when the next status read
happened to run**, not when the process died — e.g. `reviewer-msol22zr-yznb0g`
has `startedAt: 2026-08-11T11:34:32.902Z` but `completedAt:
2026-08-15T09:58:30.123Z`, four days later. The true death proxy is the job
log's last progress line before the generic message appears. I read all seven
logs directly and extracted:

| job | worktree | pid | last activity (true death, UTC) | seconds after "Turn started"/last tool call |
|---|---|---|---|---|
| `reviewer-msn9ytr1-yllwes` | issue-1217 | 63336 | 2026-08-10T13:48:10.233Z | ~12 min in |
| `reviewer-msol22zr-yznb0g` | issue-1215 | 21922 | 2026-08-11T11:35:30.493Z | ~1 min in |
| `reviewer-msopkhc4-293vhv` | issue-1217 | 3216 | 2026-08-11T13:40:57.461Z | ~8s after first assistant message |
| `reviewer-msorigsa-e00nuf` | issue-1217 | 62119 | 2026-08-11T14:35:16.264Z | ~2s after "Turn started" |
| `reviewer-msp1ijoq-g0r73d` | issue-805 | 58130 | 2026-08-11T19:15:28.991Z | ~14s after first assistant message |
| `reviewer-msu7ably-g12syz` | issue-1215 | 78162 | 2026-08-15T09:57:34.701Z | mid-review, many tool calls in |
| `reviewer-msutyqik-kuspi8` | issue-1215 | 45198 | 2026-08-15T20:31:48.013Z | mid-review, many tool calls in |

(paths: `/Users/anis/.claude/plugins/data/codex-nix-codex/state/<worktree>/jobs/<job>.log`, tails read directly)

**All seven share exactly one `sessionId`: `1551811e-645c-4038-bd19-ceff934b13c2`**,
spanning 2026-08-10 through 2026-08-15 across three worktrees, all
`kind: "plan-review"`, all with `deadlineAt` absent (no `--timeout-ms`
configured — confirming no worker-side timeout could have produced these).
This is a single long-lived Claude Code session that retried the same
worktrees repeatedly (issue-1215: 3 attempts, issue-1217: 3 attempts,
issue-805: 1 attempt) — verified from each job's own `.json` record. Because
that session kept launching *new* jobs well after each of these deaths, it had
**not ended** at any individual death time, which independently confirms §2's
conclusion that `SessionEnd` cleanup cannot be the direct cause.

`state.mjs:72-83` hashes `fs.realpathSync.native(workspaceRoot)` (SHA-256,
first 16 hex chars) to scope all state — including the broker record — **per
worktree**. So the three failing worktrees have three independent broker
sessions; a broker-replacement kill (§6) could only be triggered by a *second*
job in the *same* worktree, which existed for issue-1215 and issue-1217 (repeat
attempts) but **not** for issue-805 (single attempt) — matching the brief's
counter-evidence exactly and confirming it as a real structural gap in
hypothesis 1b for that one worktree specifically.

### 6. The plugin's own broker-teardown/self-reap logic can kill a live, in-turn worker by design — but I found no trace that it fired here

Two source-confirmed mechanisms, both capable of producing this exact
signature (process vanishes mid-turn, no app-level error, no OS crash report):

- `ensureBrokerSession()`: if a broker record exists but
  `existing.scriptPath !== scriptPath` (the *plugin's own* Nix store path
  changed, e.g. after a rebuild) **or** the 150ms-bounded
  `isBrokerEndpointReady()` probe fails, it calls `teardownBrokerSession()` on
  the existing broker, which sends `SIGTERM` to the broker's **whole process
  group** (`killImpl(-pid, "SIGTERM")`) — this reaches any app-server child
  still attached, with no check for an in-flight request.
  — `.../scripts/lib/broker-lifecycle.mjs:212-245`, `:421-436`,
  `.../scripts/lib/process.mjs:105-107`
- The broker's own supervision tick self-reaps — SIGTERM, escalating to
  `SIGKILL` on the app-server child after a 2s bound — whenever its record is
  found `"foreign"` (replaced by someone else) or `"orphaned"` (missing), **by
  design, even with a client actively connected**: "Whoever replaced the
  record already decided this broker is gone, so exit even with a client
  connected — it is unreachable by design now."
  — `.../scripts/lib/broker-supervisor.mjs:68-92` (comment + logic),
  `.../scripts/app-server-broker.mjs:291-323` (`reapShutdown`,
  `terminateSpawnedChild("SIGKILL")` at line 317)

A successful firing of this path is designed to leave **no artifact**: R3
("no app-server broker outlives its owners") requires a self-reaped broker to
delete its own pid file, log file, socket, and session directory
(`removeBrokerSessionFiles()`, `.../scripts/app-server-broker.mjs:228-248`).
This is by explicit design — the source comment states self-reap "leaves no
artifacts" as the closed contract from issue #9.

I searched for corroborating evidence and found none, but the search is
structurally unable to distinguish "didn't happen" from "happened exactly as
designed":
- 707 orphaned broker session directories (`cxc-*`) survive under
  `/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/`, 624 with a `broker.log`.
  These are, by construction, only the ones that **failed** to self-reap
  cleanly (a clean self-reap deletes them) — grepping all 624 logs for
  `"reason=replaced"`, `"did not exit within"` (the SIGKILL-escalation line),
  or any of the seven dead workers' pids returned **zero matches**, and no
  `broker.log`'s mtime falls inside any of the seven ±3-9 minute death windows.
- The one flake update in the window (`5fa03bb`, 2026-08-15T20:50:11+01:00,
  ~41 minutes before `msutyqik`'s death) advanced only the `codex-cli` input's
  rev (`e4e3b06...` → `edc9233...`) — verified via `git show 5fa03bb --
  flake.lock`. It did **not** touch the `codex-plugin-cc` input, which is what
  `scriptPath` in the `sameBuild` check is derived from. So this specific
  update does not mechanically explain a broker-replacement kill for
  `msutyqik`, despite the suggestive timing; I flag the timing but do not rely
  on it.

Net: mechanism 1b is real, source-confirmed, and matches the failure signature
better than any OS-level explanation I could corroborate — but I have no
positive evidence it fired, and its self-cleaning design means the absence of
evidence is not strong evidence of absence either.

### 7. Direct primary-source OS-log search found no jetsam/OOM-kill evidence at any of the seven death timestamps

Machine: `MacBookPro18,1`, `hw.memsize = 17179869184` (16 GB) — confirmed via
`sysctl hw.memsize` and `system_profiler SPHardwareDataType`. A materially
tight budget for an app-server accumulating dozens of large diff tool outputs
in its own memory per §4/§3, alongside normal desktop load (Ghostty, VS
Code/OrbStack, browser — all visible in the same period's
`/Library/Logs/DiagnosticReports/`).

Full-range search, `log show --predicate 'eventMessage contains "jetsam"'
--start 2026-08-01 --end 2026-08-16 09:00` (`/usr/bin/log show`, ~48k total
lines scanned): **zero** real jetsam-kill lines; the only matches are four
`runningboardd` "Ignoring jetsam update" lines for unrelated processes, logged
live at the moment the query itself ran.

Narrow ±3-9 minute `log show` windows around all seven true death timestamps
(§5), predicate covering `Terminated`, `SIGKILL`, `killed`, `jetsam`,
`highwater`, `Sudden Termination`, `vm_pageout`: **zero** matching kill/OOM
events in any of the seven windows (only routine, unrelated `dasd`/
`runningboardd`/`TextInputSwitcher` chatter). One data point of interest 30
seconds before `msutyqik`'s death: `PerfPowerServices` logged `kernel returned
(0) from memorystatus_control(MEMORYSTATUS_CMD_GET_JETSAM_SNAPSHOT) -- no
jetsam data available` — i.e., at that moment the kernel had no jetsam
snapshot to report, which if anything argues against an imminent jetsam event,
though this is a routine periodic call and not conclusive either way.

`DiagnosticReports` inventory for the full window (both
`/Library/Logs/DiagnosticReports` and `~/Library/Logs/DiagnosticReports`, all
files, not just ones named "codex"): four `JetsamEvent-*.ips` files exist
(2026-08-11, 08-12, 08-14, 08-15) but on inspection (`jq`) these are periodic
whole-system memory-candidate **snapshots** — every running process listed
with memory/priority fields, no `killed` field present on any entry across
1,600+ processes per report — not confirmed-kill reports. Two `node-*.ips`
crash reports exist (2026-08-11 20:06:51 and 21:51:07 local) but are
unrelated: both are a `vitest` test-runner process (`node (vitest 1)` thread
name) crashing from its own in-process V8 heap OOM
(`node::OOMErrorHandler`/`v8::internal::V8::FatalProcessOutOfMemory`, `SIGABRT`
not `SIGKILL`), running under Ghostty's process coalition
(`coalitionName: "com.mitchellh.ghostty"`), not under any codex-companion
process tree. The two "codex"-named diagnostics
(`codex_2026-08-14-165114_mbp.diag`, `codex-raw_2026-08-16-002409_mbp.diag`)
are also unrelated: the former is the ChatGPT desktop app's bundled `codex`
binary (`/Applications/ChatGPT.app/Contents/Resources/codex`, a disk-write-
quota diagnostic, `"Action taken": "none"`), the latter is a VS Code
extension's `codex-raw` self-update/install helper — neither is the
codex-companion app-server, and neither's timestamp matches any of the seven
death windows.

No native "codex" (Rust app-server) crash report of any kind exists anywhere
in the window. This absence is genuinely ambiguous: `SIGKILL`, unlike
`SIGABRT`/`SIGSEGV`, does not produce a crash report on macOS, so this is
equally consistent with (a) a real jetsam/kernel OOM kill that this machine's
retained log buffer/report set does not surface under the predicates I
searched, or (b) a plain userspace `kill()` from another process (§6's
mechanism), which also produces no crash report and no log line by default.

## Unfalsifiable with available evidence

I cannot determine, from what survives on this machine today, whether the
proximate kill was macOS jetsam/kernel OOM (§7, no direct corroboration found)
or the plugin's own broker self-reap path (§6, mechanistically closer but no
positive trace found, and self-cleaning by design). Both produce an identical
external signature — silent process death, no application error, no OS crash
report — and both leave a corroborating artifact only in a place that would
already be gone by the time of this investigation (a rotated-out unified-log
buffer entry, or a broker.log deleted by the very cleanup path that would have
run). I am stating this as a genuine unresolved fork rather than guessing.
This does **not** weaken the shared upstream trigger (§4/§3) or the
recommendation below, both of which hold under either branch.

## Actionable conclusion

Bounding review-input size (e.g., enforcing this repo's existing 400-line
gate — or an equivalent file/byte cap — *before* dispatching to a Codex
review, rather than letting an oversized diff fall through to `self-collect`
mode) would very likely prevent this class of death:

- It removes the only condition all seven failures share and none of the
  eight routinely-completing worktrees share (§4).
- It breaks the causal chain into `openai/codex#24048`'s documented failure
  mode regardless of which of 1a/1b ultimately executes the kill, since both
  require the app-server to first accumulate the large tool output that
  triggers the memory growth.
- It does not require resolving the unfalsifiable fork above to be effective.

It would not, by itself, fix the underlying upstream bug (`#24048` is real,
open, and would still bite the *next* oversized input elsewhere) or, if
hypothesis 1b is in fact the true mechanism, the broker-replacement race
itself — both are worth separate follow-up if reviews of large diffs need to
remain supported rather than gated away.

---

## Reviewer's note (added on commit, 2026-08-16)

Spot-checked on commit: `git.mjs:8-9` (2 files / 256 KB), `git.mjs:343`
(`inputMode: includeDiff ? "inline-diff" : "self-collect"`),
`broker-supervisor.mjs` ("exit even with a client connected"),
`codex --version` = 0.147.0, and `openai/codex#24048` (open, filed 2026-05-22,
~27 GB then SIGKILL, no fix) all confirmed independently and verbatim. The
§4 causal chain and the actionable conclusion stand.

**One methodological correction to §5.** The table treats each log's last line
as the "true death" timestamp, but for four of the seven that last line is the
*heal-on-read reconciliation stamp*, written whenever a later status read
happened to run — not when the process died. The last **progress** line is only
a lower bound on death; the reconciliation stamp is the upper bound. Those
windows are wide:

| job | last progress line | reconciled | death window |
|---|---|---|---|
| `reviewer-msorigsa-e00nuf` | 2026-08-11T14:35:16Z | 2026-08-16T07:41:40Z | ~5 days |
| `reviewer-msp1ijoq-g0r73d` | 2026-08-11T19:15:28Z | 2026-08-16T07:41:40Z | ~5 days |
| `reviewer-msol22zr-yznb0g` | 2026-08-11T11:35:30Z | 2026-08-15T09:58:30Z | ~4 days |
| `reviewer-msn9ytr1-yllwes` | 2026-08-10T13:48:10Z | 2026-08-11T13:44:17Z | ~24 h |
| `reviewer-msopkhc4-293vhv` | 2026-08-11T13:40:57Z | 2026-08-11T13:44:17Z | **~3.4 min** |

So the timing column must not be used to argue about mechanism — "died ~2s in"
is not established for any job whose window is days wide. This does not touch
§4 or the recommendation, both of which rest on the size correlation rather
than on timing.

**One genuine counterexample the timing does establish.** `msopkhc4` is the
only failure with a tight window, and it died within ~3.4 minutes having issued
**zero tool calls** — its log ends after a single assistant message, with no
`Running command:` line at all. Nothing was self-collected, so no large tool
output accumulated, so `#24048`'s memory path cannot explain that one. It is
also issue-1217's *second* attempt in the same worktree, which is exactly the
precondition hypothesis 1b (broker replacement) requires.

Net effect on the recommendation: bounding review-input size remains the right
first move and addresses the dominant pattern, but it should be expected to
reduce this failure class rather than eliminate it. At least one of the seven
has a different proximate cause, and the residual points at 1b — so if deaths
persist after the input bound lands, the broker-replacement path is the next
place to look, not the upstream memory bug.
