# oMLX serving GLM-5.3-Flash on `eleven-m5`

## Problem

The owner wants GLM-5.3-Flash running on the Mac Studio (M5 Ultra, 256 GB) through oMLX, tuned
for that machine and reachable by teammates over the tailnet. Nothing in the flake installs
oMLX, the default GPU memory limit is too small for the model, and nothing keeps the model loaded.

## Solution

Install the oMLX Homebrew formula from its project tap on `eleven-m5` only. A launchd daemon runs
`omlx serve` as the owner on port 8000 on every interface, with an API key from sops. A second
boot daemon raises the GPU wired-memory limit. An activation step pins the model and makes it
the default in oMLX's own settings file.

## Decisions

- **Model.** TensorFold `GLM-5.3-Flash-MLX-oQ4-MTP` (185 GB): mixed 4–8-bit oQ, validated with
  oMLX, benchmarked on a 256 GB Ultra. It is downloaded by hand into `~/.omlx/models`, not
  by activation. Native MTP stays off (its card measured it slower).
- **Install.** The tap is a flake input wired through nix-homebrew and trusted as a formula. It
  is shared by both Macs like the other taps; only `eleven-m5` lists the formula. No custom
  kernels (they need full Xcode).
- **Server.** A system daemon runs as the owner, at boot and kept alive. It decrypts
  `omlx_api_key` with the owner's age key at start and passes it in the environment, never argv.
  It runs `--host 0.0.0.0 --port 8000` and otherwise keeps oMLX's defaults (process limit RAM −
  8 GB, 100 GB SSD cache).
- **GPU memory.** A boot daemon sets `iogpu.wired_limit_mb` to 240 GiB, leaving about 16 GB for
  macOS.
- **Pinning.** Activation merges `is_pinned` and `is_default` for the model into
  `~/.omlx/model_settings.json`, creating `{"version":1,"models":{}}` if absent. It restarts the
  daemon only when that merge changed the file. The admin UI keeps owning every other key.

## Test seams

- `just build eleven-m5` and `just build mbp`: the formula, daemons and trust entry appear only
  on `eleven-m5`.
- Live on the Studio: the wired limit is set, `GET /v1/models` lists the model with the key and
  refuses without it, and a short `/v1/messages` request returns text.

## Out of scope

- A `claude-local` wrapper on the Studio (user Q5: not now).
- Custom kernels, MTP and per-request tuning.
- Distributing the API key to teammates (the owner shares it).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | TensorFold oQ4-MTP | User Q1 "recommended and optimized for the M5 256"; the only build validated with oMLX on 256 GB | pipenetwork 4-bit (plain quant), mixed 4/8 (fit risk) |
| D2 | Homebrew formula via the flake-pinned tap, Studio only | User Q2 | The `.dmg` app: not declarative |
| D3 | Listen on every interface behind a sops API key passed in the environment | User Q3 (teammates); argv is visible to all accounts | Localhost only |
| D4 | 240 GiB wired limit from a boot daemon, and the model pinned | User Q4 | macOS default ~192 GB: the model barely fits with no room for KV cache |
| D5 | Pin by a jq merge of two keys, restarting only on change | The repo's jq-merge pattern for app-owned files | Owning `model_settings.json`: the admin UI writes it too |
