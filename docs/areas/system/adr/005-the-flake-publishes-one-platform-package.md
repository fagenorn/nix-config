# ADR-system-005 — The flake publishes one platform package, and hosts install it

- **Status:** superseded by ADR-system-007
- **Decided in:** #1439

## Context

The platform existed only as parts of a home configuration: a launcher was one store file per command, and the manifest and standards were linked into `~/.agents` by Home Manager. A project's CI, which has no home configuration, could not fetch the platform (#1413). The commands also located the manifest only through `$HOME`, so a package that carries its own manifest had no way to be read without a home directory.

## Decision

- **D1, one derivation.** The flake publishes `packages.<system>.agent-platform` for `x86_64-linux` and `aarch64-darwin`, one derivation named `agent-platform` with no version in the name. Its layout is `$out/bin/<command>`, `$out/share/agent-platform/platform-manifest.json` and `$out/share/agent-platform/standards/`. The launchers are written inside it with `$out`, so the manifest a launcher reports is inside the package.
- **D2, the launcher names the root.** Each launcher exports `AGENT_PLATFORM_ROOT`, the value `$out/share/agent-platform`. `agent_platform` reads `<root>/platform-manifest.json` and `<root>/standards` when the variable is non-empty, and `$HOME/.agents/share/platform-manifest.json` and `$HOME/.agents/standards` otherwise. A set root never falls back to `HOME` and never consults it, so an unset `HOME` is no refusal under a root, and a manifest missing under the root is refused as `platform.manifest.missing` even when `HOME` holds a valid one. A root that is not absolute refuses `platform.manifest.missing` before any filesystem read. An empty value is an unset one. An explicit manifest path (`platform-status --manifest`) ignores the root. There is no new repair id. Siblings inherit the variable, so a sibling reads the same manifest. Nothing locates the package from `__file__` (`docs/standards/agent-helpers.md` rule 3).
- **D3, per-system nixpkgs.** `aarch64-darwin` builds from `inputs.nixpkgs-darwin.legacyPackages` and `x86_64-linux` from `inputs.nixpkgs.legacyPackages`, the channel each host family already uses.
- **D4, hosts install the flake output.** A host's `agentTools` is `inputs.self.packages.<system>.agent-platform`, so the installed copy is the published derivation, not a rebuild with the host's `pkgs`. The home paths stay as they were: `~/.agents/bin/<command>`, `~/.agents/standards` and `~/.agents/share/platform-manifest.json`.
- **D5, source-run children never inherit the root.** Three boundaries start processes that must read `$HOME` or a staged manifest rather than the installed package, and each drops `AGENT_PLATFORM_ROOT`: suite members (`suite_runner.member_environment`); the `guard-policy-fleet` candidate, which reads the manifest staged under its temporary `HOME` (`verify_checks._candidate_env`); and every Claude session, probe, sign-in, nudge and project question the console starts (`manager.client_environment`). The console runs under its launcher, so without the drop every agent session and each source-run test it runs would read the package's manifest. A session's own `~/.agents/bin` commands set the root again through their launchers.
- **D6, what stays home-linked.** `~/.agents/share/artifact-budget-policy.json` and `~/.agents/share/host-declaration.json` stay linked from source: the platform is the commands, the standards directory and the manifest.

## Consequences

- ADR-system-002 is amended: a command-table row is now a `bin/<command>` of the platform package, whose launcher also exports the root, rather than a separate store file.
- The `Nix Eval` job builds the Linux package, evaluates the darwin one and runs the package check; the job keeps its name and its evaluated attribute.
- Every merge to `main` is a published revision of the package: there is no tag and no version bump.
- A process started from source with an inherited root would read the package's manifest instead of `$HOME`'s; the three boundaries of D5 are the places that start such processes, and a new one must drop the variable too.
