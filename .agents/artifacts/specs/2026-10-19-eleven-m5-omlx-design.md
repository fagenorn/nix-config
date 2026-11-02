# oMLX serving GLM-5.3-Flash on `eleven-m5`

## Problem

The owner wants GLM-5.3-Flash running on the Mac Studio (M5 Ultra, 256 GB) through oMLX, tuned
for that machine and reachable by teammates over the tailnet. Nothing in the flake installs
oMLX, the default GPU memory limit is too small for the model, and nothing keeps the model loaded.

## Solution

Install the oMLX Homebrew formula from its project tap on `eleven-m5` only. A launchd daemon runs
`omlx serve` as the owner on port 8000 on every interface, with an API key from sops. A second
boot daemon raises the GPU wired-memory limit. A declarative model list is downloaded by a
third daemon and hot-swapped by oMLX; activation sets each model's alias and the default.

## Decisions

- **Model.** TensorFold `GLM-5.3-Flash-MLX-oQ4-MTP` (185 GB): mixed 4–8-bit oQ, validated with
  oMLX, benchmarked on a 256 GB Ultra. It is the default entry of the model list (D8), which a
  daemon downloads; native MTP is on (D10).
- **Install.** The tap is a flake input wired through nix-homebrew and trusted as a formula. It
  is shared by both Macs like the other taps; only `eleven-m5` lists the formula. No custom
  kernels (they need full Xcode).
- **Server.** A system daemon runs as the owner, at boot and kept alive. It decrypts
  `omlx_api_key` with the owner's age key at start and passes it in the environment, never argv.
  It runs `--host 0.0.0.0 --port 8000` and otherwise keeps oMLX's defaults (process limit RAM −
  8 GB, 100 GB SSD cache), except chunked prefill and the aggressive decode burst (D11) and the
  Splash memory budget (D12), which
  activation deep-merges into `~/.omlx/settings.json` under the same rules as D5; the admin UI
  and the auth secrets keep every other key there.
- **GPU memory.** A boot daemon sets `iogpu.wired_limit_mb` to 240 GiB, leaving about 16 GB for
  macOS.
- **Upstream fix.** Per D6.
- **Splash (D12).** oMLX 0.7.2 serves Qwen GGUFs through Splash's Metal engine with DFlash2
  speculative decoding. The `incoai/tap` Splash formula is installed beside oMLX, which finds it
  in `/opt/homebrew/bin`; a Flash-Next GGUF and its DFlash2 draft join the model list.
- **Models (D8).** A declarative list of `{ repo, alias?, default?, mtp?, include?, id?, settings? }`:
  `include` limits the download to some globs, `id` names a model whose oMLX name is not its
  directory's (a GGUF), and `settings` adds model settings. A daemon downloads each
  missing model into a staging directory, moves it into place when complete and restarts the
  server; it runs at boot and activation starts it while a model is missing. Activation merges each
  model's alias, the single default, `is_pinned = false` and its `settings` into
  `~/.omlx/model_settings.json`,
  clearing `is_default` elsewhere, and restarts the daemon only when that changed the file. The
  admin UI keeps owning every other key. `~/.omlx` is mode 0700.
- **Tap trust (D9).** nix-homebrew's trust lists are also emitted as Brewfile `trusted:` lines.

## Test seams

- `just build eleven-m5` and `just build mbp`: the oMLX and Splash formulae and the daemons
  appear only on `eleven-m5`; both Brewfiles carry the `trusted:` lines.
- Live on the Studio, Splash: `/v1/models` lists `qwen3.8-flash-next-splash` (oMLX lists a GGUF
  only while an engine can serve it) and not the DFlash2 draft, and a request to it returns text.
- Live on the Studio: the wired limit is set, `GET /v1/models` lists the model with the key and
  refuses without it, a short `/v1/messages` request to each alias returns text (the second one
  swaps models), and `~/.homebrew/trust.json` and the formula's dependencies survive a switch.

## Out of scope

- A `claude-local` wrapper on the Studio (user Q5: not now).
- Custom kernels and per-request tuning.
- Distributing the API key to teammates (the owner shares it).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | TensorFold oQ4-MTP | User Q1 "recommended and optimized for the M5 256"; the only build validated with oMLX on 256 GB | pipenetwork 4-bit (plain quant), mixed 4/8 (fit risk) |
| D2 | Homebrew formula via the flake-pinned tap, Studio only | User Q2 | The `.dmg` app: not declarative |
| D3 | Listen on every interface behind a sops API key passed in the environment | User Q3 (teammates); argv is visible to all accounts | Localhost only |
| D4 | 240 GiB wired limit from a boot daemon (the original pin is superseded by D8) | User Q4 | macOS default ~192 GB: the model barely fits with no room for KV cache |
| D5 | Model and server settings by a jq merge of only the declared keys, restarting only on change | The repo's jq-merge pattern for app-owned files | Owning `model_settings.json` or `settings.json`: the admin UI writes both, and `settings.json` holds the auth secrets |
| D6 | Carry upstream PR #4644 (GLM-5.3 MTP-tail config check) as a repo patch that activation re-applies only when it is missing; it goes quiet once a release carries it and warns if the code moved | Live load failed on oMLX 0.7.1rc1 with transformers 5.17 (45 layers vs 46 `mlp_layer_types`); with the patch the model loads and answers | Waiting for upstream; editing the checkpoint's `config.json` |
| D8 | Serve a declarative model list with LRU hot-swap and no pin: GLM-5.3-Flash (default) plus Jundot's Qwen3.8-Flash-Next oQ4e-mtp | User: fastest strong Qwen3.8 and hot-swappable models; 185 + 106 GB exceeds the 240 GB GPU limit | Pinning GLM plus a co-resident Qwen3.8-27B (16 GB): slower dense model |
| D9 | Emit the nix-homebrew trust lists as Brewfile `trusted:` lines | Live: `brew bundle cleanup --force` resets trust.json to the Brewfile, which dropped the tap formula's dependencies on the first install | Re-running `brew trust` after the bundle: cleanup already ran without trust |
| D10 | Native MTP on for both models | Measured on the Studio: GLM ~63 → ~80 tok/s, Qwen ~120 → ~144 tok/s (single stream) | Off, as GLM's card advised from an M3 Ultra run |
| D11 | `scheduler.chunked_prefill = true` and `server.burst_decode_mode = "aggressive"` | Measured on live team traffic: aggregate decode stays ~54 tok/s at any concurrency; chunked prefill took per-request speed with 4+ in flight from 6.5 to 13.8 tok/s and memory-pressure events from 110 to 63 per hour; the burst was neutral to slightly positive | MTP `mtp_adaptive_max_depth = 2`: about −20% aggregate, so the adaptive default (3) stays |
| D12 | Upgrade oMLX to 0.7.2 (D6's patch still applies) and serve `unsloth/Qwen3.8-Flash-Next-GGUF` UD-Q4_K_XL (111 GB) on Splash as `qwen3.8-flash-next-splash`, with a 256K context and a 200 GB Splash budget, beside the MLX build; the DFlash2 draft is `is_hidden` | User: Splash for Qwen3.8, best parallel performance without losing intelligence; picked UD-Q4_K_XL. Splash runs no Flash-Next MLX checkpoint. Its concurrency is its KV pool, which oMLX otherwise sizes for one context window | ISTA-DASLab Q2_0 (Splash's benchmark quant): 2-bit; Q5/Q6_K_XL: larger, slower; bf16 KV: halves the pool for a small gain |
| D7 | The Studio never sleeps and restarts after power loss or a freeze | User: "make sure it doesn't shut down"; it slept and dropped off the tailnet | Leaving macOS's default sleep |
