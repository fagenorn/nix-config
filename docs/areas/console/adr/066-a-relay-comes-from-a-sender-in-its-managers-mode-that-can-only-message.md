# ADR-console-066 — A relay comes from a sender in its manager's mode that can only message

- **Status:** accepted
- **Decided in:** #1230

## Context

The console tells a running manager to read its inbox by a relay: a short-lived `claude-account run -p` session that sends one peer message by session name. The client's cross-session messaging rule (https://code.claude.com/docs/en/cross-session-messaging.md, "Control inbound messages") delivers a message only when sender and receiver are in the same permission class. A receiver that prompts for permissions holds a message only when the sender identifies itself as bypassing; a receiver that bypasses holds every message unless the sender also bypasses. A held message in a background session waits with no deadline while no terminal is attached, so on 17 Nov a manager running in `bypassPermissions` was deaf to the console (#1228).

Setting `crossSessionInbound: accept` on the manager would deliver every message, but it accepts every local session as a sender, which no manager should do. A sender that always bypasses would instead deafen every `auto` manager, and after #1228 switches bypass off every manager is `auto`.

## Decision

**D1. The sender runs in its manager's mode.** A relay or continue carries `--permission-mode bypassPermissions` exactly when the sprint's newest logged mode (ADR-console-060 D4) is `bypassPermissions`. A sprint whose mode is `auto` or has none logged gets a relay with no `--permission-mode`. The service decides it under the ingest lock (`_relays_in_bypass`) and passes it as `Nudge.sender_bypass`.

**D2. The sender can only message.** Every relay and continue carries `--tools SendMessage,ListAgents`, `--allowedTools SendMessage` and `--strict-mcp-config` with no `--mcp-config`, so a bypassing sender can use no other built-in tool and loads no MCP server. Each variadic list is followed by a flag, and the prompt stays the last element and the only one carrying text for the manager.

**D3. The wake and the revive are unchanged.** They resume the manager's own session with the sentence as its prompt and send no peer message, so they ignore `sender_bypass`.

## Consequences

- Bypass stays off until the owner decides (ADR-console-060 as amended by #1228).
- While every manager is `auto`, a relay differs from before only in its tool set.
- A relay logs no `permission` member (ADR-console-060 D2), so it never changes the fold. A relay's mode follows the fold: a manager whose mode changed without a logged row would get a relay in the wrong class, which its receiver holds.
