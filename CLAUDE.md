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
just update           # nix flake update (advances ALL inputs, incl. claude-code)
just gc 5             # delete old generations (keep 5) + nix-store --gc
just install <IP>     # remote-provision a fresh NixOS box over SSH
```

There is **no test/lint suite** — `just build` (a successful Nix evaluation + build) is the verification step. After editing any `.nix`, run `just build` before claiming success; switch only when asked. CI (`.github/workflows/flake-checker.yaml`) only runs DeterminateSystems flake-checker on push/daily — it does not build or deploy.

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

## Key conventions & gotchas

**zsh rc is assembled from fragments.** `home/{darwin,linux}-common.nix` set `programs.zsh.initContent` to `mergeFilesOrdered [ ../data/zshrc/<platform> ../data/zshrc/common ]`. `initContent` is a `lines`-typed option, so this is **merged with** (not replacing) the base `programs.zsh.initContent` in `home/default.nix` (which sources zsh-vi-mode). Fragments are ordered by numeric filename prefix **per directory**, platform dir first then common: `<platform>/00-*` → `common/50-*` → `common/51-*`. Edit shell behavior in `data/zshrc/`, not in the `.nix` files.

**Secrets via sops-nix + age.** Encrypted store is `secrets/secrets.yaml` (recipient in `.sops.yaml`); the age private key must already exist at `~/.config/sops/age/keys.txt` on the machine (it is *not* in the repo; `~/.ssh/id_ed25519` is a decryption fallback). `home/common/sops/default.nix` declares which secrets get decrypted and exports `GITHUB_TOKEN`/`HF_TOKEN` into the shell. To add a secret: `sops secrets/secrets.yaml` to add the encrypted value, then declare `sops.secrets.<name>` in that module and reference it via `${config.sops.secrets.<name>.path}`.

**Homebrew (darwin only).** Casks/brews live in `hosts/common/darwin-common.nix` (`onActivation.cleanup = "zap"` removes anything unmanaged on every switch). Taps — including the **self-authored `homebrew/palmier-tap/`** — are wired in `lib/helpers.nix` under `nix-homebrew`:
  - The tap key **must** carry the `homebrew-` prefix (`fagenorn/homebrew-palmier`) because nix-homebrew uses the key verbatim as the on-disk `Library/Taps/<key>` dir, even though the cask is referenced as `fagenorn/palmier/palmier-pro`.
  - Third-party taps must be listed in `trust.casks` (Homebrew 6.0 requires tap trust + nix-homebrew forces no-API), or `brew bundle` refuses them during activation.
  - `palmier-pro.rb` uses `version :latest` + `sha256 :no_check` with `greedy = true` → re-fetches the newest `.dmg` on every switch (intentionally non-reproducible, always-latest).

**Claude Code is declaratively managed** by `home/common/claude-code/default.nix` — read it before touching any Claude Code config on this machine:
  - The binary is pinned to the `claude-code` flake input (`sadjow/claude-code-nix`, hourly-tracked official native build, autoupdater pre-disabled); it advances only on `just update` + rebuild. Substituted from `claude-code.cachix.org` (substituter declared in `hosts/common/darwin-common.nix`, darwin only).
  - `~/.claude/settings.json` is generated from the `settings` attrset in `default.nix` but **materialized as a writable copy** via a home-manager activation script — *not* via `programs.claude-code.settings` (a read-only store symlink there would break `/config`). **Edit settings in `default.nix`; do not edit `~/.claude/settings.json` directly (it resets on rebuild).**
  - Global guidance has one source at `home/common/agent-guidance/AGENTS.md`, exposed as both `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. Global skills similarly come from `home/common/agent-skills/skills/` and are exposed to both agents; Superpowers is agent-native and UI/UX Pro Max is generated once for both.
  - The `palmier-pro` MCP server (HTTP on `127.0.0.1:19789`) is merged into `~/.claude.json` by an idempotent jq activation script — not the module's mcpServers option (which broke subcommands). New MCP servers should follow that same jq-merge pattern, never overwriting `~/.claude.json` wholesale.

**Other notable bits:** Ghostty on darwin is stubbed to `pkgs.hello` (the package is broken on darwin); Linux uses the real one. The dock app list is split into `hosts/common/darwin-common-dock.nix` so it can be swapped per-host (`mkDarwin` picks `hosts/darwin/<hostname>/` if present, else the dock variant). Catppuccin (macchiato) is enabled globally. Git commits are SSH-signed by default with `~/.ssh/id_ed25519`.
