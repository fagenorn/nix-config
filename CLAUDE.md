# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Personal Nix flake managing **nix-darwin** (macOS, host `mbp`) and **NixOS-on-WSL** (host `anis-desktop`), with **home-manager** for user config. Forked from `ironicbadger/nix-config`. Pinned to the 25.11 release channels (`stateVersion` is `25.05`).

## Commands

All workflows go through the `justfile` (recipes are gated by `[macos]`/`[linux]` and auto-detect the host via `hostname`):

```sh
just                  # = `just switch`: build then activate the config for this host
just build            # build only, no activation — use this to validate a change
just trace            # build with --show-trace (debug eval errors)
just switch           # build + darwin-rebuild/nixos-rebuild switch (may prompt for sudo)
just build mbp        # target a specific host explicitly
just show-claude-settings # print the generated settings JSON (builds first)
just agent-instruction-budget # the Instruction Budget gate against origin/main (--raise-label for a labelled raise)
just update           # nix flake update (advances ALL inputs, incl. claude-code)
just gc 5             # delete old generations (keep 5) + nix-store --gc
just install <IP>     # remote-provision a fresh NixOS box over SSH
```

There is **no unit-test suite for the Nix configs** — `just build` (a successful Nix evaluation + build) is the local verification step. After editing any `.nix`, run `just build` before claiming success; switch only when asked. CI (`.github/workflows/ci.yaml`) runs on pull requests and on push to `main`: `Flake Checker` annotates `flake.lock` health without failing, and **`Nix Eval` evaluates `nixosConfigurations.anis-desktop` on Linux and is one of the two contexts `.github/branch-protection.json` makes required on `main`, the other being `Instruction Budget` (`.github/workflows/instruction-budget.yaml`)** — once `just protect-main` has been applied, `gh pr merge` (including `--admin`) is refused until both are green on a branch that is up to date with `main`, and direct pushes to `main` are refused outright (a commit that has never reached the remote can carry no status). CI does not build, deploy, or evaluate `darwinConfigurations.mbp`, so macOS configuration verification remains the author's local responsibility. `just protect-main` / `just unprotect-main` / `just show-protection` manage that protection from `.github/branch-protection.json`.

## Architecture

`flake.nix` → imports `vars/` (→ `myvars`) and `lib/` (→ `libx`) → builds `darwinConfigurations.mbp` and `nixosConfigurations.anis-desktop` via `libx.mkDarwin` / `libx.mkNixos` (both in **`lib/helpers.nix`** — the structural heart of the repo).

Each builder assembles a layered module list:

```
hosts/common/common-packages.nix      # packages shared by ALL hosts/platforms
hosts/common/{darwin,linux}-common.nix # system-level: nix settings, OS defaults, homebrew (darwin)
home-manager (as a nix-darwin/NixOS module)
  └─ home/default.nix                  # platform-agnostic user config
  └─ home/{darwin,linux}-common.nix    # platform-specific user config
```

Two repo-specific helpers in `lib/helpers.nix` drive almost everything — understand them first:

- **`scanPaths <dir>`** — auto-imports every subdirectory and `.nix` file in `<dir>` (excluding `default.nix` itself). This is why `home/default.nix`, `home/darwin-common.nix`, and `home/linux-common.nix` end in `imports = (libx.scanPaths ./common/./darwin/./linux)`. **To add a module, just create `home/common/<name>/default.nix` (or `home/darwin/...`, `home/linux/...`) — it is picked up automatically. Never maintain an import list.**
- **`mergeFilesOrdered [dirs]`** — reads regular files from each dir in sorted order and concatenates their contents. Used to build the zsh rc from `data/zshrc/` fragments (see below).

`myvars` (`vars/default.nix`: `username`, sops paths) and `libx` are threaded through `specialArgs`/`extraSpecialArgs`, so every module receives them as function args. Change the username in one place (`vars/default.nix`) and it propagates.

**Agent helper package.** Agent-workflow Python is moving into one standard-library package, `agent_tools`, under `python/` (with its `pyproject.toml`). The `just` recipes that run package code set `PYTHONPATH` to `python/`, and tests run commands as `python -m agent_tools.<module>`. The remaining Python helpers are still flat scripts under `home/common/agent-skills/scripts/`, and move in cluster by cluster, while `docs/standards/agent-helpers.md` sends all new helper code to the package. Each command's contract (review packaging, `verified-tree`, `launch-scope`, `lane-triage`), the transaction core, the retained review evidence and the #117 attempt-lifecycle decision are in [`python/README.md`](python/README.md); new detail of that kind goes there, not here.

## Key conventions & gotchas

**zsh rc is assembled from fragments.** `home/{darwin,linux}-common.nix` set `programs.zsh.initContent` to `mergeFilesOrdered [ ../data/zshrc/<platform> ../data/zshrc/common ]`. `initContent` is a `lines`-typed option, so this is **merged with** (not replacing) the base `programs.zsh.initContent` in `home/default.nix` (which sources zsh-vi-mode). Fragments are ordered by numeric filename prefix **per directory**, platform dir first then common: `<platform>/00-*` → `common/50-*` → `common/51-*`. Edit shell behavior in `data/zshrc/`, not in the `.nix` files.

**Secrets via sops-nix + age.** Encrypted store is `secrets/secrets.yaml` (recipient in `.sops.yaml`); the age private key must already exist at `~/.config/sops/age/keys.txt` on the machine (it is *not* in the repo; `~/.ssh/id_ed25519` is a decryption fallback). `home/common/sops/default.nix` declares which secrets get decrypted and exports `GITHUB_TOKEN`/`HF_TOKEN` into the shell. To add a secret: `sops secrets/secrets.yaml` to add the encrypted value, then declare `sops.secrets.<name>` in that module and reference it via `${config.sops.secrets.<name>.path}`.

**Homebrew (darwin only).** Casks/brews live in `hosts/common/darwin-common.nix` (`onActivation.extraFlags = [ "--zap" "--force-cleanup" ]` with `cleanup = "none"` removes anything unmanaged on every switch; the comment above it in that file explains the shim and when to drop it). Taps — including the **self-authored `homebrew/palmier-tap/`** — are wired in `lib/helpers.nix` under `nix-homebrew`:
  - The tap key **must** carry the `homebrew-` prefix (`fagenorn/homebrew-palmier`) because nix-homebrew uses the key verbatim as the on-disk `Library/Taps/<key>` dir, even though the cask is referenced as `fagenorn/palmier/palmier-pro`.
  - Third-party taps must be listed in `trust.casks` (Homebrew 6.0 requires tap trust + nix-homebrew forces no-API), or `brew bundle` refuses them during activation.
  - `palmier-pro.rb` uses `version :latest` + `sha256 :no_check` with `greedy = true` → re-fetches the newest `.dmg` on every switch (intentionally non-reproducible, always-latest).

**Claude Code is declaratively managed** by `home/common/claude-code/default.nix` — read it before touching any Claude Code config on this machine:
  - The binary is pinned to the `claude-code` flake input (`sadjow/claude-code-nix`, hourly-tracked official native build, autoupdater pre-disabled); it advances only on `just update` + rebuild. Substituted from `claude-code.cachix.org` (substituter declared in `hosts/common/darwin-common.nix`, darwin only).
  - `~/.claude/settings.json` is generated from the `settings` attrset in `default.nix` but **materialized as a writable copy** via a home-manager activation script — *not* via `programs.claude-code.settings` (a read-only store symlink there would break `/config`). **Edit settings in `default.nix`; do not edit `~/.claude/settings.json` directly (it resets on rebuild).**
  - `just show-claude-settings` builds and prints the settings JSON. Four lifecycle verbs (`git push`, `gh pr create`, `git branch -d`, `gh pr merge`) and adding the `instruction-budget-raise` label are adjudicated by a fail-closed `PreToolUse` hook, `home/common/claude-code/lifecycle_guard.py`; it also refuses `nohup`, `setsid` and `disown` in every repository, so run long or detached work with the Bash tool's `run_in_background: true` or `launch-scope exec`. Any change to the guard must keep the adversarial table in `tests/test_claude_permission_guard.py` green. The guard's full semantics, the guard/core decision and the plugin wiring are in [`home/common/claude-code/README.md`](home/common/claude-code/README.md); new detail of that kind goes there, not here.
  - Global guidance has one source at `home/common/agent-guidance/AGENTS.md`, exposed as `~/.claude/CLAUDE.md` (via `programs.claude-code.memory`) and `~/.codex/AGENTS.md` (via `home/common/agent-guidance/default.nix`). Global skills likewise have one source at `home/common/agent-skills/skills/`, reaching Claude through `skillsDir` and Codex through the whole-directory links at `~/.agents/skills/` — whole-directory because Codex ignores a skill whose `SKILL.md` is itself a symlink. Skill packaging (Codex's `~/.codex/skills/` runtime state, Impeccable, retired skills, the Claude-only `codex-collaboration` and `orchestrate-issues` skills and Codex's stub), the `.superpowers/` path homes and launch-fenced writers are in [`home/common/agent-skills/README.md`](home/common/agent-skills/README.md); new detail of that kind goes there, not here.
  - Lifecycle helper contracts — `workflow-state build-delivery` (delivery objects are built, never hand-composed), host admission, the anti-zombie bound with `mark-progress`, and `resume-pack` — are in `home/common/agent-skills/README.md` § Lifecycle helpers; new helper-contract detail goes there, not here.
  - `patches/agent-plugins/codex-plugin-cc.patch` is zero-context: apply it with `git apply --unidiff-zero`, reconcile two branches' edits by merging the patched source trees and regenerating (never by merging the patch text), and read the scratch clone or the built store path, never the patch text, to assert anything about the patched source. The full editing and test procedure is in `home/common/claude-code/README.md`; new detail of that kind goes there, not here.
  - The `palmier-pro` MCP server (HTTP on `127.0.0.1:19789`) is merged into `~/.claude.json` by an idempotent jq activation script — not the module's mcpServers option (which broke subcommands). New MCP servers should follow that same jq-merge pattern, never overwriting `~/.claude.json` wholesale.

**Local-model Claude Code (Linux only).** `home/linux/claude-local/default.nix` puts a `claude-local` wrapper on PATH: it points the *same* pinned Claude Code binary at the NInfer server in `~/Projects/ninfer` (Qwen3.8-27B NVFP4 on the 5090, `devenv shell -- start-server`, `127.0.0.1:8080`), which speaks Anthropic Messages natively — `/v1/messages` with tool-call streaming and thinking. Do **not** reach for `--bare` to shrink the ~24k system prompt this repo generates — it skips hooks, which disables the `PreToolUse` lifecycle guard; the prompt is cache-read anyway, so it is not the cost it looks like. The env choices, the classifier's request shape, the shim and the fan-out limits are in `home/linux/claude-local/README.md` and the comments of its `default.nix` and `anthropic-shim.py`; new detail of that kind goes there, not here.

**Other notable bits:** Ghostty on darwin is stubbed to `pkgs.hello` (the package is broken on darwin); Linux uses the real one. The dock app list is split into `hosts/common/darwin-common-dock.nix` so it can be swapped per-host (`mkDarwin` picks `hosts/darwin/<hostname>/` if present, else the dock variant). Catppuccin (macchiato) is enabled globally. Git commits are SSH-signed by default with `~/.ssh/id_ed25519`.
@.agents/instructions/bootstrap.md
