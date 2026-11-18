# ADR-hosts-009 — A Mac reached only over SSH runs the owner's services at boot

- **Status:** accepted
- **Decided in:** #1290

## Context

A launchd user agent loads in the owner's `gui/<uid>` domain, which exists only while the owner is logged in at the screen. eleven-m5 is reached only over SSH and its automatic login is off, so nobody is ever logged in there as the owner, and its login agents (the console, verify-pending, the secrets decryption and the cache proxy) never loaded. ADR-verification-008 recorded the same limit for verification on a Mac.

## Decision

A host that sets `ownerServices.atBoot` (eleven-m5) runs the owner's services as four launchd daemons in the system domain: `org.nixos.agent-console`, `org.nixos.verify-pending`, `org.nixos.claude-cache-proxy` and `org.nixos.sops-nix`. Each runs as the owner through `UserName`, with `HOME` set to the owner's home, and starts at boot with nobody logged in.

The console and verify-pending daemons are built from the same definitions as their login agents. The cache proxy and the secrets decryption are built from their home-manager agents, so the program, the environment and the logs stay declared where they were, and those two home-manager agents are disabled on that host.

The activation cleans up the legacy plists at the start of the launchd step, after the preflight checks and before any daemon loads. It boots each legacy login agent out of the owner's session when there is one, and deletes its plist. It stops the activation when a login agent will not boot out, so that no daemon starts beside a loaded copy of it.

The secrets decryption is reloaded by the daemon reload when its definition changes, and runs again at boot. To run it by hand: `sudo launchctl kickstart system/org.nixos.sops-nix`. Home-manager's own decryption step is emptied on that host, because it addresses `gui/<uid>`.

mbp keeps its login agents.

## Consequences

- A console started outside the configuration (run by hand, or a hand-installed system service) must be booted out and its definition removed before the first activation of this change. Otherwise the console daemon cannot bind port 27184 and launchd restarts it every few seconds, and the `owner-services` check reads not met while the port's listener is not the console job.
- A by-hand reload of any of the four uses `sudo launchctl kickstart system/<label>`.
- Verification on that host runs without a login (ADR-verification-008, amended in #1290).
- The `owner-services` check reads only a page activation (the console's result, log and `activation.finished` row). The first activation of this change is run by hand over SSH, because the page is down while the stopgap is removed, and it leaves nothing for the check to read; once the host runs the merge the page offers no Activate for that same commit. The check therefore stays not yet (75) until the page activates a later commit that contains the merge, which needs no action beyond the next change to the default branch that the page offers. The block's 14 day expiry is the bound on that wait.
- The console on this host answers on loopback, as everywhere: another account on the shared Mac reaches the port and the page token in it, the boundary ADR-console-008 accepts (loopback trust). Running the console as a daemon of the owner does not widen that exposure beyond the login agent's; narrowing it (an owner-only listener or independent authentication) is a console decision, not part of starting the owner's services at boot.
