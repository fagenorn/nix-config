# eleven-m5 inference settings

`omlx.nix` owns model aliases/defaults, selected performance settings, and the
patches required by the Homebrew oMLX installation. `omlx-configure` is generated
as a user command and called by system activation. It checks every patch before
applying any, recursively merges owned settings, preserves unrelated UI settings
and server secrets, and writes one reason line to `.omlx/.restart-needed` for each
change the server reads only at start: an applied patch, a changed declared key or a
created file. It prints the reasons as `restart_reasons`.
It also removes the preset directories an earlier version created (each marked by a
`.omlx-*-preset` file) and lists them as `removed_presets`; it refuses one that holds
anything but symlinks and JSON files.
Incompatible patches fail activation. It leaves the entries of undeclared models
untouched. When the admin UI makes an undeclared model (or the JarBird model) the
default, the declared default yields to it so there stays one default, and returns
at the next activation after that default is cleared.

`omlx-restart` restarts the server only while it is idle or stopped. While `/health`
reports a loaded model, a preload or an answer it cannot read, it prints the
`oMLX: restart deferred (...)` line and keeps the marker; `omlx-restart --now`
applies it regardless. Activation and the downloader both go through it, never
through a kill of their own. While a restart is deferred, an admin-UI save can
overwrite the declared change in the files; the next activation writes it again.
Applying `omlx-configure` alone does not restart active work.

The JarBird model `GLM-5.3-Flash-Abliterated-MLX-4bit`, installed by oMLX's admin
downloader under `models/grant-ai/`, is pinned so it loads at start and is never
evicted, and the memory guard is `custom` at a 192 GB ceiling, because the pinned
182 GB model did not fit under the dynamic ceiling (175.66 GB). The pin is declared
in `omlx.nix`; the 192 GB ceiling is read from `memory-budget.nix`.

## What else an activation restarts

nix-darwin reloads every launchd daemon whose plist changed, but an activation
never unloads `org.nixos.omlx` while it is loaded. It installs the changed plist
(the serve script embeds the store path of `secrets/secrets.yaml`, so any secrets
edit changes it) and adds `launchd plist changed: org.nixos.omlx` to
`.restart-needed`. `omlx-restart` applies it as an unload and `load -w` of the job
only while the server is idle, or with `omlx-restart --now`. While the reload is
pending, launchd keeps running the old generation's serve script. Each held
activation roots the script `launchctl print` shows launchd running (a reboot or a
manual unload and load changes it) at `/nix/var/nix/gcroots/omlx-held-serve`, so `just gc` cannot remove the
script KeepAlive relaunches after a crash or a jetsam kill. The reload removes the
root. A pending reload with a model loaded waits for an idle server, and
`omlx-restart --now` applies it at once.

oMLX is the only held daemon. Every other daemon still reloads when its plist
changes: `omlx-models`, `iogpu-wired-limit` (which re-runs the sysctl),
`colima` and `docker-socket`, the GitHub runners, `fseventsd-trim`, `memory-floor`, `memory-census`, and the owner's
`agent-console`, `verify-pending`, `claude-cache-proxy`, `omlx-memory-watch` and
`sops-nix` daemons. The serve script carries the relaunch gate, so a changed
`floorGiB` or `fastSampleSeconds` becomes a pending oMLX reload at the next
activation; a changed `omlxJetsamPriority` restarts only `memory-floor`. Homebrew's
`onActivation.upgrade` can replace the oMLX install; the running server keeps its
loaded code, and the re-applied patches become a deferred restart.

`verify-pending`: a changed plist is unloaded and loaded with `load -w`. That loads a
job that was booted out and clears a `launchctl disable`, and RunAtLoad starts a pass.
An unchanged plist leaves a booted-out job out, and the postActivation kick's
`kickstart` of it fails harmlessly.

The Anthropic patch accepts Claude Code's `output_config.effort` and preserves
valid explicit `chat_template_kwargs.reasoning_effort`. Qwen4-exp templates
receive low→low, medium→medium, and unsupported high/max→xhigh. An advertised
high alias remains valid. Other model families receive their original tier.
Unknown API effort strings and invalid
effective Qwen template overrides fail explicitly. Omitted or null effort uses
the model setting. Forced model keys retain precedence, as do Anthropic thinking
controls over unforced enable_thinking values.

Both served Qwen3.8 variants default to medium effort and a 4096-token thinking
budget. This bounds routine reasoning while preserving an explicit request's
`thinking.budget_tokens` override. Disabled thinking stays disabled even when the
default budget is attached to generation parameters. GLM's reasoning settings
are not changed. A budget is a reasoning-token bound, not a latency guarantee.

## Memory budget

The host has 256 GiB. oMLX is held to a fixed ceiling, 10 GiB is kept back as a
floor, and everything else (the Colima VM, verification runs, CI jobs and macOS)
must fit in what is left. `memory-budget.nix` declares every number below, and
oMLX, Colima and the watcher read theirs from it. `tests/test_memory_budget.py`
fails when the allowances no longer sum to at most the others budget, so a
number changed in one place cannot drift from the rest.

The budget is `totalGiB` - `omlxCeilingGiB` - `omlxOverCeilingGiB` - `floorGiB`
= 256 - 192 - 2 - 10 = 52 GiB for everything but the model. The allowances add
up to 8 + 1 + 2 x 4 + 4 x 3 + 12 + 5 = 46 GiB, so 6 GiB are unallocated (the 6 GiB the
floor gave up, see "Why the floor is 10 GiB"). The
5 GiB for the agent's Claude sessions had to come from somewhere, and
`verifyRunGiB` went from 6 to 4 to pay for it. The 52 GiB others budget is the
owner's capacity number: whether it holds is a question for the lead.

| Name | Value | What it bounds | Source |
|---|---|---|---|
| `totalGiB` | 256 | The host's physical memory. | `sysctl -n hw.memsize` prints 274877906944. |
| `omlxCeilingGiB` | 192 | The oMLX memory guard's fixed (`custom`) ceiling. | `/health` shows `final_ceiling` 206158430208, which is 192 GiB. |
| `omlxOverCeilingGiB` | 2 | How far the server's footprint may pass its ceiling before the budget stops holding. | Estimate of the overshoot the guard allows; the server's footprint read 187360249992 B (174.5 GiB), under its ceiling. |
| `colimaGiB` | 8 | The Colima VM's memory, passed as `--memory`. | `~/.colima/default/colima.yaml` shows `memory: 8`. |
| `colimaOverheadGiB` | 1 | What the VM's host-side processes take beyond its memory. | Estimate, checked against the day line. |
| `verifySlots` | 2 | Verification runs that may hold a slot at once. | Read from `verify_slots` in `home/common/agent-skills/host-declarations/eleven-m5.json`. |
| `verifyRunGiB` | 4 | One verification run's memory (provisional). | Estimate; `peak_others_gib` in the day line tests it. |
| `agentSessionsGiB` | 5 | What the agent's Claude sessions take together. | 4.5 GiB of Claude sessions at the 24 Nov panic. |
| `ciRunners` | 4 | CI jobs that may run at once, one per runner. | Counted in `default.nix` from `config.services.github-runners`, not declared in `memory-budget.nix`. |
| `ciJobGiB` | 3 | One CI job's memory (provisional). | Estimate; `peak_others_gib` in the day line tests it. |
| `macosGiB` | 12 | What macOS and its daemons take, fseventsd included (provisional). | Estimate; `peak_others_gib` in the day line tests it. |
| `fseventsdLimitGiB` | 4 | fseventsd's share inside `macosGiB`, enforced by `fseventsd-trim`. | See "What makes fseventsd grow". |
| `floorGiB` | 10 | Memory held back from every other use; a loaded sample with less available raises `low_memory`. | The owner's choice of 25 Nov, the lead's recommendation; see "Why the floor is 10 GiB". |
| `floorSamples` | 3 | Consecutive samples under `floorGiB` before `memory-floor` ends a workload. | The owner's choice. |
| `floorGraceSeconds` | 5 | How long a workload has to exit on SIGTERM before SIGKILL. | The owner's choice. |
| `floorMarginGiB` | 16 | How far above `floorGiB` `memory-floor` samples at the fast interval. | The owner's choice. |
| `floorFallGiB` | 2 | A fall in available memory between two samples that also earns the fast interval. | The owner's choice. |
| `floorMinTreeGiB` | 1 | The smallest workload `memory-floor` ends under the floor; a smaller tree frees too little to matter. | The owner's choice; on 25 Nov the floor ended 47 trees of 0.0 to 0.1 GiB that freed nothing. |
| `fastSampleSeconds` | 2 | `memory-floor`'s sampling interval near the floor or while memory falls, and the relaunch gate's polling interval. | The owner's choice. |
| `slowSampleSeconds` | 10 | `memory-floor`'s sampling interval otherwise. | The owner's choice. |
| `runBoundGiB` | 24 | The footprint over which one workload is ended whatever memory is free: over `verifyRunGiB` and `ciJobGiB`, at most `othersBudgetGiB`. | Leaves a verification run or CI job its allowance several times over, and stops one workload from taking the whole others budget. |
| `othersBudgetGiB` | 52 | What the model and the floor leave for the rows above. | Computed: `totalGiB` - `omlxCeilingGiB` - `omlxOverCeilingGiB` - `floorGiB`. |
| `omlxJetsamPriority` | 190 | oMLX's jetsam priority; the kernel ends the lowest band first. 180 is its default band (`JETSAM_PRIORITY_DEFAULT`), where unmanaged processes such as the agents' test workers run. `memory-floor` raises the running pid to 190 and never lowers a higher value. | The xnu `kern_memorystatus.h` and `kern_memorystatus.c` sources linked in "The memory floor", and the 24 Nov `jetsam_priority ... from=180` line of `/var/log/memory-floor.log`. |
| `fseventsdRestartMinutes` | 60 | The shortest time between two `fseventsd-trim` restarts. | See "What makes fseventsd grow". |
| `unownedAlertGiB` | 5 | Unowned memory over which the watcher sends `unowned_memory`, once per episode. | The lead's 25 Nov reading: 35 GiB unowned before an oMLX restart, about 0 after. |

`verifyRunGiB`, `ciJobGiB` and `macosGiB` are provisional: nobody has measured
them. The day line shows whether they hold.

### Why the floor is 10 GiB

The pinned model holds 175 of the host's 256 GiB, so an idle host has about 21 GiB
available. A 16 GiB floor left 5 GiB for every test, lint and CI run of the three
projects that share the host, and on 25 Nov it ended 47 workloads between 05:45 and
07:20 UTC. On 25 Nov the owner chose 10 GiB, the lead's recommendation, which leaves
about 11 GiB above the floor on an idle host.

The floor exists to act before the kernel's compressor fills and the watchdog
panics the host, as it did on 24 Nov. The fastest fall in available memory seen so far is about 39 GiB in one minute,
0.65 GiB a second, an average over that minute; a shorter burst can fall faster. At
its fast interval, `memory-floor` nominally needs about 11 s from the first sample
under the floor to SIGKILL: three samples 2 s apart (`floorSamples` x
`fastSampleSeconds`, 6 s) and a 5 s SIGTERM grace (`floorGraceSeconds`). That is
about 7 GiB at the fastest one-minute rate, so for a steady decline with an eligible
workload a 10 GiB floor leaves an estimated 3 GiB of margin where 16 GiB left 9.

The margin is an estimate, not a guarantee. A burst that drains more than 7 GiB in
under 11 s outruns it, and so does a fall with no eligible workload, one of at least
`floorMinTreeGiB` that frees enough to matter. The daemon also sleeps after each
sample, and it scans processes after each sample, so a scan slow under load adds to
the 11 s; peak sub-minute drain is unmeasured, and scan latency under load is named
by the `slow_reading` lines (see the memory floor below). If a
fall is ever seen that is faster than 39 GiB in one minute, or the reaction time
grows, raise the floor again in `memory-budget.nix`.

### How the numbers were measured

Read on 2026-11-24, with nothing restarted:

- Memory: `sysctl -n hw.memsize` printed 274877906944. `curl` of the server's
  `/health` showed `loaded_count` 1 and `final_ceiling` 206158430208.
- The server's footprint: `footprint -p <omlx-server pid> -f bytes
  --noCategories` printed `phys_footprint: 187360249992 B`. The pid is the one
  `launchctl print system/org.nixos.omlx` shows.
- Used and available memory: `vm_stat` (page size 16384) gave used 203.1 GiB and
  available 52.9 GiB, so everything but oMLX held 28.6 GiB (used minus the
  footprint above).
- Colima: `~/.colima/default/colima.yaml` has `memory: 8`.
- Jetsam priority: `launchctl print system/<label>` showed `jetsam priority =
  40` for oMLX, Colima, the console, `verify-pending` and the runners before
  this change, and 180 for `com.apple.fseventsd`. Those 40s are launchd's own
  band for the job, not the kernel's value: the helper read 180 from the
  kernel for the running oMLX.
- The 19 Nov kill: `/Library/Logs/DiagnosticReports/JetsamEvent-2026-11-19-002938.ips`
  lists oMLX at 174.82 GiB, then `dotnet` at 11.2 GiB, the VM at 7.63 GiB,
  `JarBird.Gateway.Tests` at 5.42 GiB and another `dotnet` at 4.34 GiB. Test
  processes of a CI job alone took 21 GiB.

"Others" is the memory used minus oMLX's own `phys_footprint`. The watcher counts
it only on samples with a model loaded and the footprint read. Each finished day
is one line of `~/.omlx/memory/memory-peaks.jsonl`: `peak_others_gib` against
`others_budget_gib` says whether the others budget held, and
`omlx_jetsam_priority` against `declared_jetsam_priority` says whether the
kernel held oMLX at or above the declared priority.
`~/.omlx/memory/memory-watch.json` holds today's
values so far.

Each sample also appends one line to `~/.omlx/memory/samples/<day>.jsonl`: the
used, available, wired, anonymous and compressed bytes, and, from a census no
older than 150 s, the system and process footprints, the unowned bytes and the
top owners. The files of the last 14 days are kept. The day's line in
`memory-peaks.jsonl` gains a `peak_<figure>_gib` and a `peak_<figure>_at` for
`sys_footprint`, `process_footprint`, `unowned`, `wired`, `anonymous`,
`compressions` and `verify` (for example `peak_unowned_gib` and `peak_unowned_at`),
the `peak_owners` of the day, `census_samples` (how many samples had a census) and
`records_since`, the day the records began, so an earlier line without them is
not a day with no peak. `peak_verify_gib` is the day's largest single verify-run
tree and `peak_verify_at` its time, and `verify_runs` is the verify runs read that day.

### When you add a workload

1. Give it an allowance in `memory-budget.nix`. A VM gets a fixed memory flag
   read from that file, as Colima's `--memory` is, so its size cannot grow
   without changing the budget.
2. Keep `tests/test_memory_budget.py` green. It fails when the allowances exceed
   `othersBudgetGiB`; lower another allowance or the oMLX ceiling until it
   passes.
3. A new verification slot or CI runner is counted on its own: raise
   `verify_slots` in the host declaration or add the runner, and the budget
   counts one more of `verifyRunGiB` or `ciJobGiB`.
4. Update the table above.
5. Read the next day's line in `memory-peaks.jsonl`: `peak_others_gib` must stay
   under `others_budget_gib`.

### The memory floor

`memory-floor` is a root daemon (`KeepAlive`) that ends agent and CI workloads
when memory stays under `floorGiB`. It only ends a workload with a declared
owner: the agent user (`--agent-user`), whose processes count when their working
directory is under a worktree (`~/Projects/*/.worktrees/*`) or a verification
run's temporary directory, or when it runs below a declared session program
(`claude`, `.claude-unwrapped`; `--agent-session`): the processes below the
session's child (the shell a tool call starts) are grouped as `agent:session:<pid>`
whatever their working directory, and a session's own processes are never
members of that session grouping (one inside a declared root still joins that
rooted workload). The CI runner accounts count too: a `Runner.Worker` starts a job's
workload. A process of any other user is never ended.

Protected, whatever its owner: pids 0 and 1, the oMLX server and everything it
started, and each service process the host runs for the system.

It samples available memory every `fastSampleSeconds` when it is under
`floorGiB` + `floorMarginGiB`, or fell by `floorFallGiB` since the last sample,
or is under the floor; otherwise every `slowSampleSeconds`. After
`floorSamples` samples in a row under the floor it ends the largest workload, but
only one that can help: a workload under `floorMinTreeGiB`, or one whose
footprint added to available memory still leaves memory under the floor, is
never ended.
It signals the workload's processes with SIGTERM, deepest in the process tree
first (leaves first), waits `floorGraceSeconds`, and sends SIGKILL to what is
left, then reads memory again. If memory is still under the floor, it ends the
next largest. A workload over
`runBoundGiB` is ended at once, whatever memory is free. When no workload
it may end would bring memory over the floor, it ends nothing and logs one
`floor_unmet available_gib=<n> largest_gib=<n>` line per episode (`largest_gib` is the largest
candidate, 0.0 with none), keeps it in its record, and the sampler sends one `floor_unmet`
alert. It logs again only when memory has been over the floor and a new episode starts.

A reading slower than `fastSampleSeconds` (available memory, the service list,
oMLX's pid or the process table) logs one
`slow_reading reading=<available|services|omlx_pid|table> seconds=<n>` line and is
kept in the record (`slow_readings`, the count, and `slow_reading_recent`, the last
entries); it changes no decision.

Each kill is one line:

```
<time> memory_kill reason=<floor|run_bound> owner=<user> workload=<agent:dir|agent:session:pid|ci:user:pid|ci:user:orphans> root_pid=<pid> root="<command>" processes=<n> tree_gib=<size> available_before_gib=<n> available_after_gib=<n> signals=<term|term+kill>
```

The workload key is percent-encoded (`/` and `:` kept), so a directory name with a
space or a newline stays on one line.

It lands at once in the root daemon's `/var/log/memory-floor.log`, and within a
minute in `~/.omlx/logs/memory-watch.log`, where the owner's sampler writes it:
the root daemon writes no path the agent user can write, so it cannot write the
watcher log itself. The daemon keeps its record at
`/var/db/memory-watch/floor.json` (the kill count, the last fifty kills and
oMLX's priority); the sampler reads it, queues one `memory_kill` alert for each
new kill, and sends it through the owner's alert settings.

A gate also holds oMLX's start: the serve script runs `memory-floor gate`
before it decrypts the key, and the gate waits, polling every
`fastSampleSeconds`, while available memory is under `floorGiB`. It only reads
memory and signals nothing, so a serving oMLX is never held, and launchd's
`KeepAlive` still owns the relaunch.

launchd ignores the `JetsamProperties` key in the oMLX plist: `launchctl print
system/org.nixos.omlx` shows `jetsam priority = 40` and `jetsamproperties
category = daemon` while the plist carried 100, and launchd takes a daemon's
priority from the category in the sealed
`/System/Library/LaunchDaemons/com.apple.jetsamproperties.Mac.plist`, whose
entries are Apple's labels. That 40 is launchd's own band for the job, not the
kernel's value for the running process. So the plist no longer carries the key,
and `memory-floor` sets `omlxJetsamPriority` on the running pid with
`memorystatus_control`, which needs root. It sets it on the first sample and
after each relaunch, so a changed `omlxJetsamPriority` needs a restart of
`memory-floor` only, and oMLX gets it without a restart.

The kernel ends the lowest band first, and a process nobody manages sits in its
default band, 180 (`JETSAM_PRIORITY_DEFAULT`), as the agents' test workers do.
`memory-floor` therefore only raises: it sets the priority when the kernel's
value is below `omlxJetsamPriority` and never lowers a higher one, which it logs
once per pid as `jetsam_priority_kept`. `memory-floor` refuses a declared value
outside 181 to 210, the highest band the kernel accepts. Each set logs the
value before it, the declared one and the value read back right after it
(`jetsam_priority ... from=180 to=190 after=190`). Sources:
[the bands](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/sys/kern_memorystatus.h#L45-L84),
[the order jetsam ends them in](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_memorystatus.c#L6497-L6551)
and [the set validation](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_memorystatus.c#L3080-L3101).

The record keeps the priority it read at the start of each sample, before any
set, and counts how often it found the value below the declared one again after
a successful set (`omlx_priority_resets`). The read-back in the log line shows
the set took; the record's value is what the kernel held between samples. The
sampler puts the record's value in `omlx_jetsam_priority`, so the day line shows
whether the kernel kept it, and queues `jetsam_priority_unset` when the call
failed or the resets are above zero.

### Unowned memory

The `memory-census` daemon runs as root every minute and runs `footprint -a --sysFootprint
--noCategories` (only root can read every process's footprint). It replaces
`/var/db/memory-watch/census.json` (directory `0755`, file `0644`) and logs to
`/var/log/memory-census.log`.

Unowned memory is the `sys_footprint` of that report minus footprint's own `total footprint`, and may
be negative. The watcher never adds up the processes' footprints itself, because that double-counts
shared memory such as Postgres shared buffers. Each record carries `census_seconds`, the time
`footprint -a` took. A report with a non-empty `errors` list is an incomplete census: it records an
`error` and no figure, and so does a timeout, a failed run or output that is not parseable.

Each sample line also ends with `events`, what changed since the previous sample. `ram_disk_attached` and
`ram_disk_detached` come from `hdiutil info -plist` (the `ram://` images, named by their whole disk and
size, so a disk replaced at the same device by one of another size is a detach and an attach).
`vm_started` and `vm_stopped` come from the pid in Colima's own `~/.colima/_lima/colima/vz.pid`, counted while
that pid is a live process: other Virtualization processes are not Colima's. `ci_job_started` and
`ci_job_ended` come from the `Runner.Worker` pids of `ps -axwwo pid=,args=`, and `floor_kill` from the new
entries of the floor record. `verify_started` and `verify_ended` come from the live `verify-slot run`
local processes of that listing (not a remote run through `ssh`), and `verify_run` (when the slot was
held, from `held_from` to `held_until`, with `tree_peak_bytes` and `tree_peak_at`) from
the lines the verify-slot history gains. `verify-slot run` measures its command's tree every 2 s while the
command runs and writes the largest reading into its history line, so a verify run is never missed between
two samples (a peak shorter than one read interval can be). A peak before midnight read after it stays out
of both days. The first sample of a source records a baseline and no event, and a
source that could not be read changes nothing. A CI job or a RAM disk that starts and ends between two samples
is not recorded, because those are read as a snapshot each minute.

### Alerts

Alerts go to the owner's Telegram bot. The owner sets it up on the console page,
which writes `~/.config/host-alerts/telegram.json` (mode `0600`, owned by the
owner) with `enabled`, `bot_token` and `chat_id`.

When the file is missing, unreadable, too open or incomplete, or when Telegram
does not accept the post, the alert goes to `~/.local/state/host-alerts/alerts.log`,
the error is logged in `~/.omlx/logs/memory-watch.log`, and the watcher exits 3
on every sample until the alert is sent. With `enabled` false, alerts are
recorded in the alerts log only.

There are nine kinds:

- `jetsam`: the kernel's memory killer ended oMLX.
- `low_memory`: available memory fell under `floorGiB` while a model was loaded
  (once per episode).
- `fseventsd_restarted`: `fseventsd-trim` restarted fseventsd.
- `fseventsd_held`: fseventsd was over its limit again inside the restart
  interval and was left running.
- `fseventsd_restart_failed`: the restart's kill failed, so fseventsd stays over
  its limit (once per episode).
- `memory_kill`: `memory-floor` ended an agent or CI workload; one alert per kill.
- `floor_unmet`: memory stayed under `floorGiB` and `memory-floor` had no
  workload it may end that would bring it over (once per episode).
- `jetsam_priority_unset`: `memory-floor` could not set oMLX's kernel jetsam
  priority, or the value did not hold after a set (once per episode).
- `unowned_memory`: unowned memory passed `unownedAlertGiB` (once per episode).

### What makes fseventsd grow

`fseventsd` is the macOS file-event daemon. `fseventsd-trim` runs as root every
minute, reads its `phys_footprint`, and restarts it when it passes 4 GiB, at most
once an hour (`fseventsdRestartMinutes`). Over the limit again inside that hour
it does not restart it and the `fseventsd_held` alert is sent. It writes the
size to `/var/db/memory-watch/fseventsd.json`, and the watcher puts the largest
in the day line as `peak_fseventsd_gib`. A restart is safe: launchd runs it with
`KeepAlive`, so it comes straight back, and its clients rescan.

Its jetsam priority, 180, is the kernel's default band and below oMLX's 190, so
under memory pressure the kernel ends fseventsd before oMLX. That is why a
growing fseventsd is ended before the model is.

What was read, re-read on 2026-11-24 with the same read-only commands
(`launchctl print system/com.apple.fseventsd`, `sudo -n /usr/bin/footprint -p
<pid> -f bytes --noCategories` and `find ~/Projects -name node_modules`):

- `phys_footprint: 5210544 B` at 10.5 h after the lead's restart, with 149
  `node_modules` directories and 116 worktree directories present. At 11.7 h
  it read `phys_footprint: 6504904 B` (peak 11796936 B) with 160 and 121.
- The lead's reading was 17.7 GB after 35 h and 10 MB after the restart.
- `JetsamEvent-2026-11-20-002944.ips` lists fseventsd as the largest process,
  at 51.53 GiB.
- Diagnostic reports exist for the 22 Nov `disk writes` and the 23 Nov `cpu usage`
  resource limits.
- About 110 `fsevent_add_client` registrations a minute came from command-line
  clients (`claude` among them).
- `/System/Volumes/Data/.fseventsd` held 2.1 GB.

The directory count is not the cause: the same directories were present at 5 MB
and at 51 GiB. So no exclusion is applied. An exclusion changes which paths are
indexed or logged, not fseventsd's buffering for each client. The trim's
record and `peak_fseventsd_gib` date the next growth, which is what to compare
with the clients running then.

## Retiring a model

Deleting a `models` entry stops its download and its declared settings, but leaves
its weights on the host: delete `~/.omlx/models/<directory>` (the repository name
after the slash, or the admin UI's directory) by hand, then apply the change with
`omlx-restart --now` when the server may pause. Its entry in `model_settings.json`
is left as the admin UI keeps it.

Run `nix build --no-link .#checks.aarch64-darwin.omlx-adapter` for the portable
adapter/configuration tests, then `just build eleven-m5` for the host. The restart
gate and the declaration (the pin, the memory guard and the restart wiring) are
covered by `tests/test_omlx_restart.py` and `tests/test_omlx_declaration.py` in
Agent Workflow Tests. CI builds
the corresponding x86_64-linux check as part of the required Nix Eval job. The
check uses the pinned oMLX flake input and immutable real Qwen template, parsing
the real schema and executing the real Anthropic endpoint to engine preflight.
GPU inference is covered separately by deployed Claude-shaped smoke requests.

After a Homebrew update, incompatible patches require checking upstream before
regenerating or removing them. Two patches are applied: the GLM fix tracks
upstream PR4644, and the effort patch is the local compatibility change for
nix-config issue410. Both were last checked against oMLX 0.8.3, which still
needs both.
