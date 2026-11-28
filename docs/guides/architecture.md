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

**.NET solution.** [ADR-system-007](../areas/system/adr/007-agent-tools-moves-to-dotnet-under-one-reference-graph.md) moves `agent_tools` to a .NET solution rooted at `dotnet/`, one project per area with its tests beside it, while the Python package keeps every command not yet moved. A project references only the projects its row lists, each `.csproj` sets `DisableTransitiveProjectReferences`, and one architecture test holds this table; adding an edge is a reviewed change to both. The pairs Release–Verification, Release–Delivery, Claims–Guard, Delivery–Guard and Console–Guard are forbidden. The architecture test in `dotnet/Hosts.Tests/Architecture/` parses the table below (one row per project, references comma separated or `none`), checks it against its own list of the record's nine projects and 31 edges, and lets a test project `<P>.Tests` reference `<P>` and `<P>`'s row. The flake builds every production project of the solution as `packages.<system>.agent-tools-dotnet` (the `agent-tools` executable) and builds them again with the test projects, whose tests it runs, as `checks.<system>.agent-tools-dotnet-tests` on x86_64-linux and aarch64-darwin, from the NuGet lock `dotnet/deps.json` that the check's `fetch-deps` regenerates; `agent-platform` links the package's executable at `libexec/agent-platform/agent-tools`, on no PATH; the required `.NET Solution` job in `ci.yaml` builds both over a cached Nix store. Each time a push run of CI on `main` completes, `.github/workflows/job-time.yaml` runs the `agent_tools.delivery.job_time` reader, which takes the `.NET Solution` job's wall times from its last 10 green runs and, when their median is not under 240 seconds, files one issue saying so, marked `<!-- agent:job-time v1 -->`, with at most one open; the verify check `home/common/verify-pending/checks/dotnet-job-wall` reads the same times for the runs after a merge.

| Layer | Project | References |
|---|---|---|
| L6 | Hosts (composition root: the command table, launchers' targets, host daemons) | Console, Delivery, Verification, Release, Guard, Claims, ProjectContract, System |
| L5 | Console | Delivery, Verification, Release, Claims, ProjectContract, System |
| L4 | Delivery | Verification, Claims, ProjectContract, System |
| L3 | Release | Guard, Claims, ProjectContract, System |
| L3 | Verification | Guard, Claims, ProjectContract, System |
| L2 | Claims | ProjectContract, System |
| L2 | Guard | ProjectContract, System |
| L1 | ProjectContract | System |
| L0 | System (the forge transport: the `gh` calls) | none |

Each shared format has one owner module and, while its area is half moved, exactly one writer. Python writes every format today except the command ids and the profile `.claude.json` that `claude-account add` creates. The slice that flips the row of a format's writing command changes its Writer cell to .NET in the same change.

| Format | Owner project · module | Writer |
|---|---|---|
| `events.sqlite3` (`events` table) | Console · `EventStore` | Python |
| `activation.result`, `activation.log` | Console · `Activation` | Python |
| Not-yet exit code 75 | Verification · `CheckOutcome` | Python |
| Command ids | Hosts · `CommandTable` | `lib/agent-tools.nix` rows |
| Engine step ids | Delivery · `EngineSteps` | Python |
| `gh` calls | System · `Forge` | Python `forge_api` for Python callers, `Forge` for .NET ones |
| Engine run files `events.jsonl`, `run.json` | Delivery · `EngineLedger` | Python |
| Claude profile `.claude.json`, created by `claude-account add` | Console · `ClaudeProfiles` | `claude-account` shell (`jq` copies an existing `~/.claude.json`) |
| Claude trust files, updated after creation | Console · `FolderTrust` | Python |
| `needs-verification` label | Verification · `HeldIssues` | Python |
| `<!-- agent:... -->` markers | Claims · `ForgeMarkers` | Python |
| Issue-body acceptance criteria | Claims · `IssueBody` | Python |
| Fleet registry `registry.json`, `.agents/state` root | ProjectContract · `AgentPlatform` | Python |
| `.agents/project.json` | ProjectContract · `Resolver`, `Adoption` | Python |
| Release profile grammar and adapter catalog | ProjectContract · `ReleaseProfile` | Python |
| Memory-watch files, cache-proxy log | Hosts · `MemoryWatch`, `CacheProxy` | Python |
| Lint timing record | ProjectContract · `Conformance` | Python |
| Release transaction `state.json` | Release · `TransactionStore` | Python |
