# ADR-console-066 — A named colleague reaches the console only through Tailscale Serve on a guest port

- **Status:** accepted; amended by ADR-console-077
- **Decided in:** #1235, #1237, #1263

## Context

The console answers only a loopback `Host` and places one write token in its page, so whoever loads the page is the owner (ADR-console-008). The owner wants to share it with one named colleague over Tailscale Serve, the tailnet-only reverse proxy the Tailscale client runs on the Windows host of the WSL machine. This record fixes the trust boundary before any code lets a second kind of visitor in. It changes no code; the slices that build it follow this record, and a statement here that a later slice confirms says so.

## Decision

**D1. What a forged identity header can do.** Serve adds a login header such as `Tailscale-User-Login` to the tailnet requests it proxies. Any other local process can send the same header to the console's loopback port; on this host WSL runs in mirrored networking, so a Windows process reaches that port too. Such a process can already read the page token from the page or from the `page-token` file and act as the owner (ADR-console-008). A forged header therefore gains it nothing it did not have. This record does not claim to stop it: loopback trust stays the boundary, and the rules below keep a guest from becoming the owner, not a local process from becoming one.

**D2. How Serve traffic is told apart.**

- Serve proxies to a second loopback port of the console, the guest port, never to the owner's port.
- Every request on the guest port is a guest request or is refused. It is a guest only when its `Host` is the tailnet name the owner configured on the page (`<host>.<tailnet>.ts.net`) and it carries exactly one login header naming a listed colleague (`<colleague-login>`).
- The owner's port stays as it is today. It also refuses any request carrying a Tailscale identity header or `X-Forwarded-For`, so a Serve misconfigured onto it never makes a guest the owner.
- A guest page carries a guest token of its own, never the owner's.
- Serve on the Windows host refuses connections from its own machine, so the read-only probe of #1237 could not run before that slice merged. By the owner's decision of 17 Nov it merged with the strict rule: a guest-port request is admitted only when its `Host` is exactly the configured tailnet name, with no port form, and exactly one `Tailscale-User-Login` header names a listed colleague; anything else is refused. The console keeps one diagnostics reading of the last request on the guest port: the `Host` it carried, how many login headers arrived, whether it came through Serve (`X-Forwarded-For`), whether it carried the probe header, and whether it was admitted or refused and why, never a login value. Only the owner's state carries it, never a guest's. The first real request from another tailnet node settles the rule after merge: the held check `home/common/verify-pending/checks/console-guest-door` reads that reading on the owner's loopback port (expiry 30 days), met when the `Host` is exactly the tailnet name in force, Serve sent one login header of its own and a client-sent `forged-probe@example.invalid` did not arrive. A reading that shows otherwise goes to the owner, who decides how the rule above changes.

**D3. What stays owner-only.** Confirming a release or any card marked production or paid; spend; accounts and sign-in; host activation; project registration; the access list itself; stopping or dropping a sprint; every manager route, which keeps its sprint secret. A guest sees only their listed projects' sprints, cards and notices, may state a goal there, and on sprints they started may approve the brief, request changes to it (`/api/reply`), answer questions and message the manager. Every guest action records who did it. Built in #1263: a guest write is admitted on the guest door as its reads are (ADR-console-077 D4), then needs the guest token and that origin; a guest row records the colleague's login as by; an owner row records none; a question that carries a look or a before-and-after pair is a look before merge and stays the owner's, and so does every question the manager marks `owner_only`, which the service refuses a guest's answer to: the manager marks one on every permission escalation, every overlap with another sprint's claim and every release, paid or production decision (see the manager contract).

**D4. The commands.** The lead runs these from this WSL host through the Windows Tailscale client; the guest port is the number the console reports for it. Never use Funnel: it is public and unauthenticated, and no step here needs it. Tailscale is never installed inside WSL.

```sh
TS='/mnt/c/Program Files/Tailscale/tailscale.exe'
# on, in the background, HTTPS on the tailnet name, proxying to the guest port
"$TS" serve --bg --https=443 http://127.0.0.1:<guest-port>
# status
"$TS" serve status
# off again
"$TS" serve --https=443 off
```

The page is then at `https://<host>.<tailnet>.ts.net/`. The only step left to the owner is sharing the machine with the colleague in Tailscale's admin page. The real tailnet name and any real login appear nowhere in the repository, the tracker or a picture.

## Considered Options

- Proxying Serve to the owner's port and trusting the identity header there: any local process could forge it, and a Serve misconfigured onto the owner's port would make a guest the owner.
- Funnel: it makes the console public and unauthenticated.
- Tailscale inside WSL: the Windows client already runs Serve, and a second node would add an identity to manage.

## Consequences

- A guest is only as trusted as Serve's header: the guest port's rule is a second line, not a defence against a local process.
- The owner's port gains a refusal of identity headers, which a probe through Serve may refine. The held check of #1237 reads the guest port only, so that refusal stays as written: every `Tailscale-` header and `X-Forwarded-For`.
- Related: ADR-console-008.
