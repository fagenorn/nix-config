# ADR-console-078 — The guest door takes its tailnet name from this host's Tailscale client

- **Status:** accepted
- **Decided in:** #1305

## Context

ADR-console-077 D4 compares the one `X-Forwarded-Host` with "the tailnet name the owner configured", which the console keeps as a `sharing.tailnet` row in its log. The log in force was rescued from a host that is gone, so its row names another tailnet. Serve on this host forwards this host's own name, so every listed colleague would be refused, and nothing on the page says why. A typed name drifts again on the next move. By the lead on 19 Nov, the name must be this host's own, read from this host's Tailscale, and Serve stays off until this lands.

## Decision

**D1. The name is read from this host's Tailscale client.** The console runs `tailscale status --json` with the same client the `--tailscale` option names for the Serve status, and takes the `Self` node's `DNSName`, with its trailing dot removed and lowercased. The name is kept only when it is a `<host>.<tailnet>.ts.net` name. It is read on the same one-minute cadence as the Serve status, kept in memory only and never in the log.

**D2. One name for admission, the reading and the origin.** This amends ADR-console-077 D4: the one `X-Forwarded-Host` must equal the name read in D1, no longer the name the owner configured. The reading's forwarded-host form, the Serve state and the guest picture's `https://` origin use the same name. Every other rule of ADR-console-066 and ADR-console-077 stands.

**D3. No name, no guest.** While sharing is on and the client cannot be read, its status has no `Self` name, or the name is malformed, the guest door refuses every request, the `/api/whoami` probe included, fail closed, with the reason `name_unread`. One request is judged by one reading of the switch, the list and the name, and the owner's access list says so in one plain line.

**D4. The owner's access list turns sharing on or off and takes no name.** `POST /api/share-tailnet` takes exactly `{"shared": true}` or `{"shared": false}`; any other body, one still carrying a name included, is `400` `bad sharing`. The access list shows the name read in D1.

**D5. The row from before.** A stored `sharing.tailnet` row from before (`{"tailnet": "<host>.<tailnet>.ts.net"}`) still means sharing is on, and its name is never used for admission. A new row is `{"shared": <true|false>}`.

## Considered options

- Keeping the typed name and warning when it differs from the read one: it still admits nobody until it is retyped, and it drifts again.
- Taking the name from the keys of the Serve config: they are absent while Serve is off, so the page could not show the name before Serve is set up.
- The machine's hostname: it is neither the MagicDNS name nor the tailnet.

## Consequences

- Moving the console to another host needs no change on the page.
- A host whose client cannot be read shares with nobody.
- The held check `console-guest-door` judges a request against the read name.
