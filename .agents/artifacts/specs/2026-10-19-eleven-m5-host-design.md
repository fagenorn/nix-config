# Mac Studio `eleven-m5` as a second nix-darwin host

## Problem

The new Mac Studio should run this flake like the MacBook Pro (`mbp`) does. It is the owner's
workstation and also a machine teammates reach over the owner's tailnet. Today every darwin host
gets the MBP's full app list, its personal app tweaks and the owner-only Nix trust, and the flake
has no entry for a second Mac or for other people's accounts.

## Solution

Add `darwinConfigurations.eleven-m5` (aarch64-darwin) built with `mkDarwin`, with the same owner
account `anis` as the MBP. Split the Homebrew app list into a shared core plus a per-host part,
so the Studio gets only the core. Personal home modules turn on only on hosts that install the
app they configure. The Studio's host module also declares teammate accounts (SSH key only, no
admin), key-only SSH, and its own dock. Both Macs run the self-hosted GitHub runners.

## Decisions

- **Host identity.** The flake attribute, `networking.hostName` and the SSH alias are all
  `eleven-m5`. The `justfile` picks the config from the hostname, so it works with no changes
  once the first switch has renamed the machine.
- **Owner account.** The owner gets a new admin account `anis` on the Studio. The `yellow` setup
  account is removed once `anis` has switched successfully. `myvars.username` stays global, so
  there is no per-host username.
- **Apps.** The shared darwin module keeps only Google Chrome, Helium, Ghostty, OrbStack and
  Tailscale. The MBP's host module adds back every other cask, plus `libmsquic` and its current
  dock. Taps and tap trust stay shared and unchanged. The Studio's host module sets a dock with
  Helium and Ghostty.
- **App-coupled home config.** The AeroSpace, darktable and SpotX modules and the palmier-pro MCP
  registration each turn on only when the host's `homebrew.casks` contains their cask. On NixOS
  there are no casks, so all of them stay off; the palmier MCP stops being registered there. The
  wallpaper stays on for every darwin host.
- **Teammates.** In the Studio host module, a list of `{ name, uid, keys }` becomes nix-darwin
  `knownUsers` accounts: standard (non-admin) accounts with zsh, a created home and
  `openssh.authorizedKeys`. They have no password and are not in `trusted-users`. The list ships
  empty, with a comment showing how to add an entry.
- **SSH server.** The Studio enables `services.openssh` with password and keyboard-interactive
  logins turned off. Teammates get terminal access only; Screen Sharing is not configured.
- **Secrets.** `anis` on the Studio uses the MBP's age key, copied over once. `.sops.yaml`
  does not change. Teammate accounts get no secrets.
- **Remote access.** The `eleven-m5` SSH matchBlock (user `anis`) points at the tailnet name
  `eleven-m5.mink-fort.ts.net`. The owner shares the node from their personal tailnet; sharing
  and ACLs are done outside Nix.
- **Runners.** The Studio uses the existing runner module unchanged. Its runners register as
  `eleven-m5-<repo>` with label `eleven-m5`, next to the MBP's.

## Test seams

- `nix build` of `darwinConfigurations.{mbp,eleven-m5}.system` (`just build <host>`) and
  `nix eval` of `nixosConfigurations.anis-desktop`. These are the repo's existing verification
  steps, and the NixOS eval is the CI `Nix Eval` gate.
- A comparison of evaluated values: the MBP's `homebrew.casks` names and dock before and after
  must be identical, and the Studio's cask set must equal the shared core.
- A live check on the Studio after the first switch: `hostname`, `ssh eleven-m5` as `anis` with
  the key, a password login refused, and `brew list --cask` showing only the core.

## Out of scope

- Screen Sharing or GUI access for teammates.
- Teammates' dotfiles or a managed team profile (they use system packages plus `nix`/`devenv`).
- Tailscale node sharing and ACLs (done in the admin console).
- Real teammate entries (the list ships empty).
- Making the taps per-host.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One macOS account per person; the owner is `anis` (admin), teammates are standard key-only accounts | User Q7/Q8 | One shared team account: exposes the owner's secrets, records nothing per person, and access can't be removed for one person |
| D2 | Host name `eleven-m5` for the flake attribute, hostname and SSH alias | User Q3/Q6 | `studio` |
| D3 | Shared core casks = Chrome, Helium, Ghostty, OrbStack, Tailscale; the rest move to the MBP host module | User Q12 | Gating each cask by a host flag in darwin-common: one list full of conditions |
| D4 | Home modules tied to an app turn on when their cask is in `osConfig.homebrew.casks` | The rule that tweaks come only with their app (Q12); DRY | A separate per-host flag list that can drift from the casks |
| D5 | Studio uses the MBP's age key | User Q5 (dedicated owner account) | A second sops recipient: re-encryption for no benefit |
| D6 | Runners on both Macs, Studio unchanged from the shared module | User Q4 | Studio only |
| D7 | Key-only sshd, SSH-only access for teammates | User Q9 (accepted recommendation) | Password SSH or Screen Sharing now |
| D8 | Teammates get only system packages, no home-manager profile, no Nix trust | User Q10; YAGNI | A managed team profile |
