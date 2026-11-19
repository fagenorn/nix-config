# ADR-console-077 — The guest door on eleven-m5 is a Unix socket only Serve and the owner can open

- **Status:** accepted; amended by ADR-console-078, ADR-console-079
- **Decided in:** #1298, #1299

## Context

ADR-console-066 fixed how a named colleague reaches the console through Tailscale Serve, the reverse proxy only machines on the owner's tailnet can reach. It was written for anis-desktop, a WSL machine whose Windows host ran the Tailscale client, so its commands drive `tailscale.exe` from WSL and its trust argument (D1) assumes the only local processes belong to the owner. anis-desktop is gone. The console runs on eleven-m5, a shared Mac where Tailscale runs as the `tailscaled` system service (driven with `sudo tailscale`) and where other people's accounts and CI runner users also run processes. ADR-console-076 closed the owner's own port to every process that is not the owner's. By the owner's answer of 19 Nov, the guest door moves from a loopback TCP port to a Unix socket in a folder only the owner's user and the Tailscale service can open. This record amends ADR-console-066 for eleven-m5 and changes no code; the slice that builds the socket follows it.

## Decision

**D1. The guest door is a Unix socket.** The console listens for guest requests on a Unix socket inside a mode-0700 folder owned by the owner's user (the user the console runs as, ADR-console-076 D1). Serve runs as root and proxies to the socket. Every other account and every CI runner user is refused by the file system, at the folder, before the console sees anything. The guest door is no longer a loopback TCP port; ADR-console-076 D7's "unchanged" ends with this record.

**D2. A second line: the peer user.** The console also reads the user of the process at the other end of each accepted guest connection (the socket's peer credentials) and admits only root, which is the `tailscaled` service Serve runs in, and the owner's own user. Any other peer is refused before a request is read. This is a second line behind the folder's mode, not the first.

**D3. ADR-console-066 D1, restated for a shared host.** An administrator with sudo stays out of reach, as ADR-console-076 D6 says: this record does not claim to stop one, who can run as root or as the owner. No other local account can pose as a colleague any more, because it can neither open the folder nor connect as a permitted peer, so a forged login header from it never reaches the console. The Windows-era argument that a forged header gains a local process nothing no longer carries the rule.

**D4. The rule of ADR-console-066 D2 stands, except its first bullet and where the tailnet name is read.** The first bullet of ADR-console-066 D2, that Serve proxies to a second loopback port of the console, is superseded by D1: Serve proxies to the guest socket. The remaining bullets of ADR-console-066 D2 stand unchanged, except where the name is read. By the owner's answer of 19 Nov (through the lead), a request on the guest door is a guest only when it carries exactly one `Host`, exactly `localhost`, exactly one `X-Forwarded-Host`, equal to the tailnet name the owner configured (`<host>.<tailnet>.ts.net`) with no port form, and exactly one login header naming a listed colleague (`<colleague-login>`); the login check stays as it is, both names are compared lowercased as ADR-console-066 compared the `Host`, and anything else is refused (fail closed). The socket file is mode 0600 and the owner's, inside the mode-0700 folder of D1, so only root and the owner can reach it; on every guest connection the console checks the folder and the file again and refuses the connection, before reading it, while either is not the owner's or its mode is wider, that is, carries any bit beyond 0700 for the folder or 0600 for the file. The owner's port, the guest token, the owner-only list of ADR-console-066 D3 and the diagnostics reading of the last guest request all stay as written; the reading also keeps the forwarded name, how many arrived, and whether the `Host` was `localhost`.

**D5. The commands, replacing ADR-console-066 D4's `tailscale.exe` ones.** The lead runs these on eleven-m5; `<socket-path>` is the path the console reports for the guest socket (the owner's `sharing.socket`), and Serve stays off until the slice of #1299 has landed and the lead has probed it.

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

- This amends ADR-console-066 (its D1, D4, the first bullet of its D2 and where its D2 reads the tailnet name) for eleven-m5; the rest of its D2 and its D3 stand. Admission and the probe's headers follow D4 here: `Host: localhost` and the tailnet name in one `X-Forwarded-Host`, never the tailnet name in `Host`. The `tailscale.exe` commands there are history of anis-desktop.
- ADR-console-076 D7 is superseded for the guest door; the owner's port stays as ADR-console-076 decided.
- A guest is still only as trusted as Serve's header, now with no other local account able to forge it.
