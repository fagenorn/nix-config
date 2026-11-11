# ADR-hosts-007 — The cache proxy senses limits behind an off-by-default flag

- **Status:** accepted
- **Decided in:** #849, #847, #860

## Context

The console's capacity strip needs each account's remaining share and next reset. The proxy already sees every response of every session on the host, and the unified rate-limit headers on those responses say where each account stands, so a separate usage endpoint or status-line feed is a second route to what the proxy already holds. A fault in the proxy still costs more than a feature in it earns (ADR-hosts-001).

## Decision

With `--sense-limits` the proxy reads the unified rate-limit headers of each response and the account and session named in `metadata.user_id` of each request, and posts the reading to the console's loopback `POST /api/readings`. It amends ADR-hosts-001: forwarding stays byte-for-byte unchanged, and nothing is added, retried or held for the reading. The proxy logs no header value and never logs, reports or stores a sign-in or device id; a failure to sense logs only its type. Without the flag no sensing object exists, so the command's default stays off and only the host configuration passes the flag.

## Consequences

- The readings replace the usage endpoint and the status-line feed as the quota source (#849 item 2).
- A console that is down costs a request nothing: the reports are dropped.
- Switching accounts in flight is not part of this record.
- Dropping `"--sense-limits"` from `cacheProxyArgs` and rebuilding turns the sensing off.
