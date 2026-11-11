---
area: Hosts
budget: 200 lines
---

# Hosts

Hosts covers what each machine runs for the agents: the pinned Claude Code binary and its generated settings, the account launcher, the local cache proxy and the launchers on the path.

## Language

**Account binding**:
The recorded choice of which account profile a project runs under, kept in a per-user table. `claude` reads it at launch to pick the profile directory.
_Avoid_: account mapping

**Account profile**:
A directory used as the Claude config directory for one account. The login is the profile's own, while settings, skills and plugins link to the shared ones.
_Avoid_: account

**Cache proxy**:
A loopback pass-through from Claude Code to the Anthropic API. It forwards requests unchanged and can keep idle conversations' caches warm, reorder a subagent's prefix or report limit readings to the console (ADR-hosts-007).
_Avoid_: gateway, relay

**Command table**:
The list in the agent-tools Nix library that maps each launcher name on the path to the Python module it runs. The build import-checks every module in it.

**Keepalive ping**:
A replay of an idle subagent conversation's last request with one output token, sent by the cache proxy to refresh its prompt cache entry before it expires.
_Avoid_: heartbeat

**Launcher**:
A small store-built executable on the path that runs one agent-tools command in the pinned Python environment.
_Avoid_: wrapper

**Limit sensing**:
The cache proxy's off-by-default reading of each response's unified rate-limit headers and each request's account and session, reported to the console as a limit reading (ADR-hosts-007).
_Avoid_: quota polling

**Prefix reorder**:
The cache proxy's rewrite of a subagent's first user message so that sibling subagents share one cacheable prefix. Every other request passes through untouched.
