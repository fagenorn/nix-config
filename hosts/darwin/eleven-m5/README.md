# eleven-m5 inference settings

`omlx.nix` owns model aliases/defaults, selected performance settings, and the
patches required by the Homebrew oMLX installation. `omlx-configure` is generated
as a user command and called by system activation. It checks every patch before
applying any, recursively merges owned settings, preserves unrelated UI settings
and server secrets, and writes one reason line to `.omlx/.restart-needed` for each
change the server reads only at start: an applied patch, a changed declared key, a
created file or a steering preset. It prints the reasons as `restart_reasons`.
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

nix-darwin reloads every launchd daemon whose plist changed, so an activation
restarts oMLX outside the gate whenever its serve script changes. That script
embeds the store path of `secrets/secrets.yaml`, so any secrets edit does it. The
same holds for `omlx-models`, `iogpu-wired-limit` (which re-runs the sysctl),
`colima` and `docker-socket`, the GitHub runners, `fseventsd-trim`, and the owner's
`agent-console`, `verify-pending`, `claude-cache-proxy`, `omlx-memory-watch` and
`sops-nix` daemons when their plists change. The oMLX plist also carries its jetsam
priority, so a changed budget value restarts oMLX outside the gate. Homebrew's `onActivation.upgrade` can replace the oMLX install; the running
server keeps its loaded code, and the re-applied patches become a deferred restart.

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

The host has 256 GiB. oMLX is held to a fixed ceiling, 16 GiB is kept back as a
floor, and everything else (the Colima VM, verification runs, CI jobs and macOS)
must fit in what is left. `memory-budget.nix` declares every number below, and
oMLX, Colima and the watcher read theirs from it. `tests/test_memory_budget.py`
fails when the allowances no longer sum to at most the others budget, so a
number changed in one place cannot drift from the rest.

The budget is `totalGiB` - `omlxCeilingGiB` - `omlxOverCeilingGiB` - `floorGiB`
= 256 - 192 - 2 - 16 = 46 GiB for everything but the model. The allowances add
up to 8 + 1 + 2 x 6 + 4 x 3 + 12 = 45 GiB, so one GiB is unallocated. The 46 GiB
others budget is the owner's capacity number: whether it holds is a question
for the lead.

| Name | Value | What it bounds | Source |
|---|---|---|---|
| `totalGiB` | 256 | The host's physical memory. | `sysctl -n hw.memsize` prints 274877906944. |
| `omlxCeilingGiB` | 192 | The oMLX memory guard's fixed (`custom`) ceiling. | `/health` shows `final_ceiling` 206158430208, which is 192 GiB. |
| `omlxOverCeilingGiB` | 2 | How far the server's footprint may pass its ceiling before the budget stops holding. | Estimate of the overshoot the guard allows; the server's footprint read 187360249992 B (174.5 GiB), under its ceiling. |
| `colimaGiB` | 8 | The Colima VM's memory, passed as `--memory`. | `~/.colima/default/colima.yaml` shows `memory: 8`. |
| `colimaOverheadGiB` | 1 | What the VM's host-side processes take beyond its memory. | Estimate, checked against the day line. |
| `verifySlots` | 2 | Verification runs that may hold a slot at once. | Read from `verify_slots` in `home/common/agent-skills/host-declarations/eleven-m5.json`. |
| `verifyRunGiB` | 6 | One verification run's memory (provisional). | Estimate; `peak_others_gib` in the day line tests it. |
| `ciRunners` | 4 | CI jobs that may run at once, one per runner. | Counted in `default.nix` from `config.services.github-runners`, not declared in `memory-budget.nix`. |
| `ciJobGiB` | 3 | One CI job's memory (provisional). | Estimate; `peak_others_gib` in the day line tests it. |
| `macosGiB` | 12 | What macOS and its daemons take, fseventsd included (provisional). | Estimate; `peak_others_gib` in the day line tests it. |
| `fseventsdLimitGiB` | 4 | fseventsd's share inside `macosGiB`, enforced by `fseventsd-trim`. | See "What makes fseventsd grow". |
| `floorGiB` | 16 | Memory held back from every other use; a loaded sample with less available raises `low_memory`. | The owner's choice. |
| `othersBudgetGiB` | 46 | What the model and the floor leave for the rows above. | Computed: `totalGiB` - `omlxCeilingGiB` - `omlxOverCeilingGiB` - `floorGiB`. |
| `omlxJetsamPriority` | 100 | oMLX's jetsam priority; the kernel ends lower numbers first. | `launchctl print system/org.nixos.omlx` showed `jetsam priority = 40`, the same as Colima, the console, `verify-pending` and the runners, before this change. |
| `fseventsdRestartMinutes` | 60 | The shortest time between two `fseventsd-trim` restarts. | See "What makes fseventsd grow". |

`verifyRunGiB`, `ciJobGiB` and `macosGiB` are provisional: nobody has measured
them. The day line shows whether they hold.

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
  this change, and 180 for `com.apple.fseventsd`.
- The 19 Nov kill: `/Library/Logs/DiagnosticReports/JetsamEvent-2026-11-19-002938.ips`
  lists oMLX at 174.82 GiB, then `dotnet` at 11.2 GiB, the VM at 7.63 GiB,
  `JarBird.Gateway.Tests` at 5.42 GiB and another `dotnet` at 4.34 GiB. Test
  processes of a CI job alone took 21 GiB.

"Others" is the memory used minus oMLX's own `phys_footprint`. The watcher counts
it only on samples with a model loaded and the footprint read. Each finished day
is one line of `~/.omlx/memory/memory-peaks.jsonl`: `peak_others_gib` against
`others_budget_gib` says whether the others budget held, and
`omlx_jetsam_priority` against `declared_jetsam_priority` says whether launchd
applied the declared priority. `~/.omlx/memory/memory-watch.json` holds today's
values so far.

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

### Alerts

Alerts go to the owner's Telegram bot. The owner sets it up on the console page,
which writes `~/.config/host-alerts/telegram.json` (mode `0600`, owned by the
owner) with `enabled`, `bot_token` and `chat_id`.

When the file is missing, unreadable, too open or incomplete, or when Telegram
does not accept the post, the alert goes to `~/.local/state/host-alerts/alerts.log`,
the error is logged in `~/.omlx/logs/memory-watch.log`, and the watcher exits 3
on every sample until the alert is sent. With `enabled` false, alerts are
recorded in the alerts log only.

There are five kinds:

- `jetsam`: the kernel's memory killer ended oMLX.
- `low_memory`: available memory fell under `floorGiB` while a model was loaded
  (once per episode).
- `fseventsd_restarted`: `fseventsd-trim` restarted fseventsd.
- `fseventsd_held`: fseventsd was over its limit again inside the restart
  interval and was left running.
- `fseventsd_restart_failed`: the restart's kill failed, so fseventsd stays over
  its limit (once per episode).

### What makes fseventsd grow

`fseventsd` is the macOS file-event daemon. `fseventsd-trim` runs as root every
minute, reads its `phys_footprint`, and restarts it when it passes 4 GiB, at most
once an hour (`fseventsdRestartMinutes`). Over the limit again inside that hour
it does not restart it and the `fseventsd_held` alert is sent. It writes the
size to `/var/db/memory-watch/fseventsd.json`, and the watcher puts the largest
in the day line as `peak_fseventsd_gib`. A restart is safe: launchd runs it with
`KeepAlive`, so it comes straight back, and its clients rescan.

Its jetsam priority, 180, is above oMLX's 100, so under memory pressure the
kernel ends oMLX before it. That is why a growing fseventsd costs the model
first.

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

## Neuron steering presets

A model entry's `steer.<preset>` list serves that model a second time as
`<alias>-<preset>` (for example `qwen3.5-4b-evil`). Each entry,
`"L<layer> N<neuron> <dose>"`, adds a constant `a` to neuron n's down_proj input
at every position:
`a = dose × median(‖residual leaving L‖, tokens 1:) / ‖W_down[:, n]‖`. The patch
wraps the decoder layer, since oMLX substitutes kernels for the MLP projections.
That matches adding to the MLP output only when the output joins the residual
unnormalised, so a model with a `post_feedforward_layernorm` (Gemma, for example)
is refused at load. The patch adds a steering digest to the engine's cache identity,
so a changed preset never restores cached state. It measures the medians once at load on five fixed chat prompts, where they
vary by about ±5%. `omlx-configure` keeps one directory per preset, holding
symlinks to the downloaded weights and a `steering.json`. It removes the
directories of presets that are no longer declared, and refuses to replace a
directory it did not create. A preset waits until its base model finishes
downloading; the downloader syncs it after any completed download. Each loaded preset costs its base
model's memory again.

To try candidate neurons before declaring them, run
`omlx-steer "L14 N8949 +1" "L13 N7956 -1"`. Optional flags are `--model`,
`--scale`, `--prompt`, `--max-tokens` and `--no-baseline`. For each prompt it
prints the baseline reply and then the steered one. It loads the model itself, outside the server, using oMLX's
Python and the patched module, so its output matches what a preset serves.

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
regenerating or removing them. The GLM fix tracks upstream PR4644; the effort
patch is the local compatibility change for nix-config issue410; the steering patch is
local to nix-config issue457.
