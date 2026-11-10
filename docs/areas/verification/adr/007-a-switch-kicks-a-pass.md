# ADR-verification-007 — A switch kicks a pass instead of watching a path

- **Status:** accepted
- **Decided in:** issue 632 D1, D11

## Context

Every host should run a verification pass after a system switch, because a switch is when a deployed revision changes. The obvious trigger is a watcher on `/run/current-system`. Spike S2 showed that a launchd `WatchPaths` on that link never fires, and a systemd path unit misses a switch that leaves the watched link unchanged.

## Decision

After each switch a kick script (`verify-pending-kick`) writes `~/.agents/state/verify-pending/switch-request` and starts the job without blocking. On NixOS it runs from home-manager activation, which starts after `/run/current-system` is repointed; on darwin it runs from the last nix-darwin `postActivation` entry with the new system's path, because home-manager's darwin activation runs before the link is repointed (D11). The pass waits up to 300 seconds to see the new system at `/run/current-system`. A request that lands mid-round earns one more round.

## Consequences

- On darwin the pass has to wait for the repointed link, so a switch round logs `current=timeout` when the new system does not appear within 300 seconds.
- The kick never fails the switch: it exits 0 even when the job cannot start.
- Between switches the 15-minute schedule is the only trigger.
