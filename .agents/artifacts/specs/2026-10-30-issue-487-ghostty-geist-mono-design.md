# Ghostty uses GeistMono Nerd Font — issue 487

Issue: https://github.com/fagenorn/nix-config/issues/487. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "no", "evidence": "only the Ghostty font-family string and system font package lists change; no schema, helper or public interface"}, "concurrency_or_persistence": {"value": "no", "evidence": "static Nix configuration; no locking or persisted state"}, "open_design_questions": {"value": "no", "evidence": "owner decided font and hosts; registered family name verified by fc-scan as 'GeistMono Nerd Font Mono'"}, "criteria_shape": {"value": "hit", "evidence": "4 criteria, but the [evidence] ghostty +list-fonts check needs a switch and the [human] render check has no deterministic code check"}}, "paths": ["home/common/ghostty/default.nix", "hosts/common/darwin-common.nix", "hosts/common/linux-common.nix"]}
Verdict: {"hits":["criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

D2 replaces the two predicted host-module paths with the all-hosts package module. None of these
paths is a light-lane risk path, so the verdict stands.

## Problem

The owner is moving their fonts to Geist. Ghostty, on all three hosts, still draws the terminal
in FiraCode Nerd Font Mono. Geist Mono, with Nerd Font icons, is not installed on any host, so
Ghostty cannot use it.

## Solution

1. Ghostty's `font-family` becomes `GeistMono Nerd Font Mono`. Font size and every other Ghostty
   setting stay as they are. Per D1.
2. `nerd-fonts.geist-mono` from the pinned nixpkgs becomes a system font on `mbp`, `eleven-m5`
   and `anis-desktop`, next to the existing fonts. Per D2.

## Decisions

- **The family name.** The name is `GeistMono Nerd Font Mono`. It is the typographic family that
  the package's files register. `fc-scan` reports `spacing=100` (strictly monospaced) for it.
  It is the Mono member, like the current `FiraCode Nerd Font Mono`. Per D1.
- **One declaration for all hosts.** The module that every host imports adds
  `pkgs.nerd-fonts.geist-mono` to the system option `fonts.packages`, which both nix-darwin and
  NixOS provide. The module system appends it to the darwin module's FiraCode list. On
  `anis-desktop`, fontconfig is on (`fonts.fontconfig.enable = true`), so the font registers there
  too. A prototype at 07f89813 evaluated to `fira-code-6.2`, `nerd-fonts-fira-code-3.4.0+6.2` and
  `nerd-fonts-geist-mono-3.4.0+1.401` on both darwin hosts, and to the Geist package alone on
  `anis-desktop`. Per D2.
- **No activation in the run.** The run never executes `just switch`. Before the merge it
  records build-time proof of AC3, and the owner takes the literal AC3 measurement and AC4 after
  switching. Per D3.
- **AC1 is measured the way the attribute evaluates.** Home Manager stores the Ghostty setting as a
  list (`["FiraCode Nerd Font Mono"]` at the base), so the literal `nix eval --raw` fails on every
  value. Per D4.
- **The sibling issue #486.** It also adds a system font on all hosts. Neither issue waits for the
  other. Per D5.

## Test seams

- **Host evaluation (AC1, AC2).** `nix eval --raw …programs.ghostty.settings.font-family --apply
  builtins.head` on mbp prints `GeistMono Nerd Font Mono`. Each host's
  `nix eval --json …config.fonts.packages --apply 'map (p: p.name)'` contains
  `nerd-fonts-geist-mono-3.4.0+1.401`. The built `ghostty/config` holds
  `font-family = GeistMono Nerd Font Mono`. The issue-399 acceptance record set this precedent of
  eval rows.
- **Build.** `just build` on mbp is the `nix-build` binding. An `eleven-m5` toplevel drvPath eval
  follows issue 399's D5. CI `Nix Eval` covers `anis-desktop`.
- **Pre-activation font proof (AC3).** Build mbp's `system.build.fonts`, the tree that activation
  copies into `/Library/Fonts/Nix Fonts`. Run the pinned fontconfig's `fc-scan` over its GeistMono
  files and count those whose family list contains exactly the configured family. The threshold
  is ≥ 1. The prototype counted 9.
- **Owner, after `just switch` on mbp.** Relaunch Ghostty or reload its config first, because a
  running Ghostty keeps the config it loaded. Then run the literal AC3 command, and do AC4's check
  of starship and the Helix picker.

`agent-workflow-tests` does not run, because no agent-tooling path changes.

### Grill refinements

- **The proxy is calibrated.** On mbp at the base commit, Ghostty 1.3.1's `+list-fonts` lists
  `FiraCode Nerd Font Mono`, the same family that `fc-scan` reports first for the FiraCode file
  nix-darwin installs. GeistMono takes the same path. AC3's literal count is 0 today.
- **No glossary or ADR change.** No context path is bound (`knowledge.context` unsupported), and
  every decision is a one-line config change that can be reverted.

## Out of scope

VS Code. Removing FiraCode from either font list. Moving FiraCode into the shared declaration.
Font size and the other Ghostty settings. Ghostty fallback families or codepoint maps. Starship and
Helix configuration. Geist Serif (#486). Browsers. Activating any host.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `font-family = "GeistMono Nerd Font Mono"`, a plain string with no fallback list | Issue: "exact name the installed font registers", "Prefer the strictly monospaced *Mono* family". fc-scan of the built files: typographic family `GeistMono Nerd Font Mono`, spacing 100 | `GeistMono Nerd Font`: the owner prefers the Mono member. `… Propo`: proportional. `GeistMono NFM`: the short legacy name, not the family |
| D2 | One `fonts.packages = [ pkgs.nerd-fonts.geist-mono ]` in the all-hosts package module, merged with the darwin FiraCode list | CLAUDE.md: common-packages is "packages shared by ALL hosts/platforms". the-bar DRY. Both platforms type `fonts.packages` as a list, and the prototype eval shows the merge | One entry in the darwin list plus a new linux block: the same fact in two homes. `environment.systemPackages`: macOS does not register those fonts, and AC2 measures `fonts.packages`. A Home Manager font install: also not `fonts.packages` |
| D3 | The run never switches. AC3's row records the pre-activation `fc-scan` count, with conditions saying it was taken before activation. The literal post-switch `ghostty +list-fonts` count goes to the owner with AC4, and the issue is held `needs-verification` whatever AC3's grade, because AC4 is human | CLAUDE.md: "switch only when asked". `--auto` never self-grants authority. Issue 238 D8 set this precedent. macOS Ghostty lists only registered fonts | Running `just switch` from the branch: it activates the owner's machine without being asked and may prompt for sudo. Treating the proxy as the literal measurement: its conditions differ |
| D4 | AC1 is measured as `nix eval --raw …font-family --apply builtins.head` (it must start with `GeistMono`), plus the generated config line. The criterion text is not edited | Measured at 07f89813: `--raw` fails with "cannot coerce a list to a string", and `--json` prints a one-element list | Writing the setting as a list or reshaping the option: `--raw` still fails. Editing the issue: the criterion is the owner's, and only the measurement form needs adapting |
| D5 | There is no coordination with #486. Whichever branch syncs second resolves any `fonts.packages` conflict by keeping both entries | The option is list-typed and merge order does not matter. The ship-issue integration sync handles conflicts | Waiting on #486, or one shared font module for both: it couples two independent deliveries for a one-line conflict |
