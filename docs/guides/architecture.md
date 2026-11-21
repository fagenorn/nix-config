# Architecture

`flake.nix` → imports `vars/` (→ `myvars`) and `lib/` (→ `libx`) → builds `darwinConfigurations.{mbp,eleven-m5}` and `nixosConfigurations.anis-desktop` via `libx.mkDarwin` / `libx.mkNixos` (both in **`lib/helpers.nix`** — the structural heart of the repo).

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

**Agent helper package.** All agent-workflow Python is one standard-library package, `agent_tools`, under `python/` (with its `pyproject.toml`). Each command is a module plus a row in the `lib/agent-tools.nix` command table, and `docs/standards/agent-helpers.md` binds it. The `just` recipes that run package code set `PYTHONPATH` to `python/`, and tests run commands as `python -m agent_tools.<area>.<module>` (`agent_tools.<module>` for the top-level modules `docs/standards/package-layout.md` keeps flat). Each command's contract is its module docstring, the package overview (layout, running, testing) is [`python/README.md`](../../python/README.md), and decisions are ADRs under `docs/areas/`; new detail goes where [`docs/README.md`](../README.md) routes it, not here.
