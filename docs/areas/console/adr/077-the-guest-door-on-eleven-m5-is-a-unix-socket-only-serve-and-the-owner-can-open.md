# ADR-console-077 — The guest door on eleven-m5 is a Unix socket only Serve and the owner can open

- **Status:** accepted
- **Decided in:** #1298

## Context

ADR-console-066 fixed how a named colleague reaches the console through Tailscale Serve, the reverse proxy only machines on the owner's tailnet can reach. It was written for anis-desktop, a WSL machine whose Windows host ran the Tailscale client, so its commands drive `tailscale.exe` from WSL and its trust argument (D1) assumes the only local processes belong to the owner. anis-desktop is gone. The console runs on eleven-m5, a shared Mac where Tailscale runs as the `tailscaled` system service (driven with `sudo tailscale`) and where other people's accounts and CI runner users also run processes. ADR-console-076 closed the owner's own port to every process that is not the owner's. By the owner's answer of 19 Nov, the guest door moves from a loopback TCP port to a Unix socket in a folder only the owner's user and the Tailscale service can open. This record amends ADR-console-066 for eleven-m5 and changes no code; the slice that builds the socket follows it.

## Decision

**D1. The guest door is a Unix socket.** The console listens for guest requests on a Unix socket inside a mode-0700 folder owned by the owner's user (the user the console runs as, ADR-console-076 D1). Serve runs as root and proxies to the socket. Every other account and every CI runner user is refused by the file system, at the folder, before the console sees anything. The guest door is no longer a loopback TCP port; ADR-console-076 D7's "unchanged" ends with this record.

**D2. A second line: the peer user.** The console also reads the user of the process at the other end of each accepted guest connection (the socket's peer credentials) and admits only root, which is the `tailscaled` service Serve runs in, and the owner's own user. Any other peer is refused before a request is read. This is a second line behind the folder's mode, not the first.

**D3. ADR-console-066 D1, restated for a shared host.** An administrator with sudo stays out of reach, as ADR-console-076 D6 says: this record does not claim to stop one, who can run as root or as the owner. No other local account can pose as a colleague any more, because it can neither open the folder nor connect as a permitted peer, so a forged login header from it never reaches the console. The Windows-era argument that a forged header gains a local process nothing no longer carries the rule.

**D4. The rule of ADR-console-066 D2 stands unchanged.** A request on the guest door is a guest only when its `Host` is exactly the tailnet name the owner configured (`<host>.<tailnet>.ts.net`) and it carries exactly one login header naming a listed colleague (`<colleague-login>`); anything else is refused. The owner's port, the guest token, the owner-only list of ADR-console-066 D3 and the diagnostics reading of the last guest request all stay as written.

**D5. The commands, replacing ADR-console-066 D4's `tailscale.exe` ones.** The lead runs these on eleven-m5; `<socket-path>` is the path the console reports for the guest socket, and Serve stays off until the socket is in.

```sh
# on, in the background, HTTPS on the tailnet name, proxying to the guest socket
sudo tailscale serve --bg --https=443 unix:<socket-path>
# status
tailscale serve status
# off again
sudo tailscale serve --https=443 off
```

The page is then at `https://<host>.<tailnet>.ts.net/`. Never use Funnel: it is public and unauthenticated, and no step here needs it. The real tailnet name and any real login appear nowhere in the repository, the tracker or a picture.

**D6. The held check runs on eleven-m5.** The held guest-door check `home/common/verify-pending/checks/console-guest-door` reads the console's own diagnostics reading, so it runs on eleven-m5, the host that serves the guest door.

## Considered Options

- Keeping the loopback TCP guest port: any local account on the shared Mac could reach it and send a forged login header.
- Reading the peer user alone, with the socket in a world-reachable place: the folder's mode refuses other accounts earlier and without a lookup, so it is the first line and the peer check the second.
- Funnel: it makes the console public and unauthenticated.

## Consequences

- This amends ADR-console-066 (its D1 and D4) for eleven-m5; its D2 and D3 stand. The `tailscale.exe` commands there are history of anis-desktop.
- ADR-console-076 D7 is superseded for the guest door; the owner's port stays as ADR-console-076 decided.
- A guest is still only as trusted as Serve's header, now with no other local account able to forge it.
