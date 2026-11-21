# ADR-verification-008 — Macs run verification only while a user is logged in

- **Status:** accepted; amended in #1290
- **Decided in:** issue 668, issue 705, #1290

## Context

A darwin verification job needs `gh` credentials, which this setup keeps in the login keychain, and a launchd job that can read them must run in the user's `gui/<uid>` domain. Neither exists while nobody is logged in at the console.

## Decision

On a login host (mbp) the darwin job is a launchd user agent in `gui/<uid>`, and `gh` reads its token from the login keychain. A login host has no LaunchDaemon form and no credential outside the keychain. With nobody logged in the agent never loads and no pass runs; the kick still writes the switch request, prints one `verify-pending-kick:` notice and exits 0. nix-darwin's user-agent reload step is guarded the same way, with or without a tty: `hosts/common/darwin-user-agent-reload-guard.sh` skips its `launchctl asuser` calls with one log line when `gui/<uid>` is absent, and the plist is still installed for the next login.

On a host with `ownerServices.atBoot` (eleven-m5) the job is a launchd daemon in the system domain that runs as the owner from boot, with nobody logged in (ADR-hosts-009). There `gh` reads its token from its own hosts file, not the login keychain, and the kick starts the job through `sudo -n /bin/launchctl kickstart system/org.nixos.verify-pending`. NixOS is unaffected.

## Consequences

- A host that runs its job at boot runs its checks without a login, so its host-bound checks are graded on schedule.
- A login host keeps the stale-check prompt path: a host-bound check on a Mac that stays logged out never runs; it surfaces through the stale-check owner prompt (`verify-stale-check`, cause `silent`), which another host's pass posts once the host has not reported for 7 days.
- No credential lives outside the login keychain on a login host, so there is no way to run a pass there while nobody is logged in.
