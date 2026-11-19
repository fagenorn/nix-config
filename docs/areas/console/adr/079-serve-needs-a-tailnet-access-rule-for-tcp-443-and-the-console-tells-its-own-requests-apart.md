# ADR-console-079 — Serve needs a tailnet access rule for TCP 443, and the console tells this host's own requests apart

- **Status:** accepted
- **Decided in:** #1320

## Context

Serve was turned on for the guest door on eleven-m5 as ADR-console-077 D5 says, and the lead's probe from eleven-m5 itself passed, yet no other device could reach the console. The tailnet's access rules, as this host's own packet filter shows them, let other devices reach this host on TCP 22 and TCP 8000 only. Serve listens on TCP 443, so a request from any other device times out before it reaches the console, while a node can always reach itself. The owner's Sharing panel showed the last request on the guest door, and a request this host sent to itself read like a visit. By the lead on 19 Nov: record the TCP 443 access rule where ADR-console-077 lists what Serve needs, say plainly on the panel when no request from another device has arrived, and never close the guest-door check on a self-probe.

## Decision

**D1. Serve needs a tailnet access rule for TCP 443.** This amends ADR-console-077 D5: besides the `sudo tailscale serve` commands, Serve needs a rule in the tailnet's access policy that allows TCP 443 to this host from the devices of every listed colleague (`<colleague-login>`). The tailnet's admin sets that rule in the tailnet admin console. It is never set in this repository, and the repository keeps no copy of the tailnet's policy.

**D2. Serve stays on 443.** TCP 8000 on this host is the shared oMLX server, so Serve does not move to a port the rules already allow; it stays on `--https=443`.

**D3. The console tells a request from this host apart from one from another device.** Serve sends the client's tailnet address as `X-Forwarded-For`. The console reads this host's own addresses, `Self.TailscaleIPs`, from the same `tailscale status --json` that gives it the tailnet name (ADR-console-078 D1), on the same cadence, in memory only. A guest-door request whose one `X-Forwarded-For` is one of those addresses is from this host and one with any other address is from another device. A request with no `X-Forwarded-For`, more than one, a malformed one, or no own addresses read is unknown, and unknown never counts as another device (fail closed). The diagnostics reading keeps only that result, never an address. Admission does not change.

**D4. The owner sees whether another device has reached the door.** The owner's Sharing panel says separately whether any request from another device has reached the guest door since the console started; that is kept in memory, so a restart starts it over. While sharing is on and none has, the panel says so in one line naming the likely cause: the tailnet's access rules must allow TCP 443 to this host for the people the console is shared with.

**D5. The held check counts only another device.** The held guest-door check `console-guest-door` is not met by a request from this host to itself, nor by one whose origin is unknown; it waits for the probe from another tailnet node that its trigger prescribes.

## Considered Options

- Moving Serve to TCP 8000, which the rules already allow: the shared oMLX server holds it.
- Taking a self-probe as proof: a node always reaches itself, so it proves nothing about the access rules.
- Keeping the client's address in the reading: the comparison is all the owner needs, and an address identifies someone's device.
- Reading this host's addresses from its network interfaces: the Tailscale client already names them beside the tailnet name.

## Consequences

- ADR-console-077's Status names this record; its D5 commands stand as written.
- Sharing with a new colleague needs the admin's access rule for their devices as well as their entry on the list.
- A host whose client gives no own addresses reads every guest-door request as unknown, and the held check waits.
