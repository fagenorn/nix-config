# ADR-hosts-001 — The cache proxy forwards bytes unchanged on loopback

- **Status:** accepted; amended by ADR-hosts-007
- **Decided in:** #422

## Context

Keeping a subagent's prompt cache warm and sharing a cached prefix between sibling subagents both need something between Claude Code and the Anthropic API that can see each request. That something sits on the path of every request of every session on the host, so a fault in it costs more than a feature in it earns.

## Decision

The cache proxy binds `127.0.0.1` only and, with no feature flag set, forwards each request's method, path, query and body bytes and each response's status, headers and body unchanged. It rewrites only `Host` and drops hop-by-hop headers; it adds, decodes and retries nothing. Every behaviour beyond forwarding is a flag that is off by default (ADR-hosts-002, ADR-hosts-003), and without a flag no object for it exists.

## Consequences

- Nothing outside the host can reach the proxy.
- An upstream 4xx/5xx body that arrives compressed (for example gzip) is logged as `error_body` decoded as UTF-8 with replacement characters, not as readable text, because the client's `Accept-Encoding` is forwarded verbatim without `--keepalive` and bodies are never decoded. The client still receives the body unchanged.
- A failed upstream is visible to the client as a `502` envelope or a closed connection, never as a retried success.
