# ADR-verification-008 — Macs run verification only while a user is logged in

- **Status:** accepted
- **Decided in:** issue 668, issue 705

## Context

A darwin verification job needs `gh` credentials, which this setup keeps in the login keychain, and a launchd job that can read them must run in the user's `gui/<uid>` domain. Neither exists while nobody is logged in at the console.

## Decision

The darwin job is a launchd user agent in `gui/<uid>`, and `gh` reads its token from the login keychain. There is no LaunchDaemon form and no credential outside the keychain. On a Mac with nobody logged in the agent never loads and no pass runs; the kick still writes the switch request, prints one `verify-pending-kick:` notice and exits 0. nix-darwin's user-agent reload step is guarded the same way, with or without a tty: `hosts/common/darwin-user-agent-reload-guard.sh` skips its `launchctl asuser` calls with one log line when `gui/<uid>` is absent, and the plist is still installed for the next login. NixOS is unaffected.

## Consequences

- A host-bound check on a Mac that stays logged out never runs; it surfaces through the stale-check owner prompt (`verify-stale-check`, cause `silent`), which another host's pass posts once the host has not reported for 7 days.
- No credential lives outside the login keychain, so there is no way to run a pass on a Mac while nobody is logged in.
