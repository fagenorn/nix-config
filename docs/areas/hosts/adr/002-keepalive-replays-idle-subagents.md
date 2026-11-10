# ADR-hosts-002 — Idle subagent caches are kept warm by replaying the last request with max_tokens=1

- **Status:** accepted
- **Decided in:** #423; issues 502 and 503

## Context

A subagent that waits on a tool or on its parent lets its 5-minute prompt-cache entry expire, and the next turn then pays a full cache rewrite. The spike measured, as fact 2 (`docs/spikes/cache-proxy-spike.md`), that replaying a conversation's last request refreshes the entry. The proxy cannot tell a subagent that has finished for good from one waiting to be woken.

## Decision

With `--keepalive` the proxy replays an idle conversation's last request with `max_tokens=1` and nothing else changed. A ping is due after 270 s without a touch, which is inside the 5-minute entry. A conversation is dropped at a 60-minute ceiling, when its session is no longer active, or, when its last reply was `end_turn`, once its idle period holds `END_TURN_PINGS` pings (issue 502). The candidate's headers, `authorization` among them, are held in process memory only and are never logged or written. A keepalive bug never blocks traffic: it is one `keepalive_error` line and the request goes on as if untracked.

## Consequences

- A subagent whose last reply ended its turn stops being pinged after two pings since its last thread request, about 14 minutes of cache, so one woken later pays a cache rewrite.
- Any other subagent, one pending a tool among them, is pinged while its session stays active, for up to 60 minutes. The `keepalive_end` log lines measure both costs, and `agent_tools.keepalive_pings` prices the pings (issue 503).
- A proxy restart forgets every conversation, because nothing is persisted.
- A request that enters the keepalive is sent upstream with `Accept-Encoding: identity`, so its response is readable by the tap.
