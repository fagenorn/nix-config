# Keepalive: unmarked side requests no longer reset a pending tool call — issue 501

Design for https://github.com/fagenorn/nix-config/issues/501 (parent
https://github.com/fagenorn/nix-config/issues/432). Base: `a40b1270`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#423 Dn" cites
`2026-10-25-issue-423-cache-keepalive-design.md`.

## Triage

Input: {"signals": {"contract_change": {"value": "no", "evidence": "Internal Keepalive state transitions in observe/_done; no CLI flag, log schema, outcome set or public interface changes"}, "concurrency_or_persistence": {"value": "hit", "evidence": "Lock-guarded per-conversation state ordered by request sequence across overlapping in-flight requests (#423 D27)"}, "open_design_questions": {"value": "doubt", "evidence": "Whether an unmarked request should still log a resumed end, update last_request, or be able to mark a tool pending is not fixed by the issue"}, "criteria_shape": {"value": "hit", "evidence": "AC2 is a 7-day post-switch evidence threshold that no deterministic code check verifies"}}, "paths": ["python/agent_tools/cache_keepalive.py", "tests/test_cache_keepalive.py", "python/README.md"]}
Verdict: {"hits":["concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

`cache-proxy --keepalive` exists so that a subagent waiting on a long
foreground command keeps its prompt cache: the subagent's last request ended
with `stop_reason` `tool_use`, so the conversation is *pending a tool*, the
session counts as active (#423 D8), and its candidate is pinged every 270 s
until the tool result comes back. In practice that wait is almost never
quiet. Claude Code sends small side requests in the same conversation, with
the same agent id and no cache mark on the last message (#423 D5's
`no_tail_mark`): over 2026-10-26..11-02 the mbp proxy log holds 17,094 of
them, 12,019 sent while the conversation's own request was still in flight
and 4,983 a median 9 s after a `tool_use` completed. Of the 1,077 tool waits
longer than 270 s, 976 held at least one.

Today the keepalive treats such a request as the conversation's next turn: it
advances the conversation's request sequence, clears the pending tool, stamps
the last client request and, after pings, ends the idle period `resumed`. A
side request sent after the `tool_use` completed clears the pending state
outright. A side request sent while the response was still streaming makes
that `tool_use` completion stale (#423 D27), so it never marks pending. The
side request's own timestamp keeps the session active until the next ping
moves the touch past it, and at the following due time the conversation ends
`session_idle` while the command still runs. The cache entry then dies. That
pattern accounts for 112 of the 127 issue-owner "long foreground command"
cache deaths in the 7 days to 2026-11-01, and 44 "task notification after end
of turn" deaths.

## Solution

A `no_tail_mark` request becomes a **side request**: the keepalive sees it
only as session activity while it is in flight. It no longer moves the
conversation's request sequence, its pending tool, its last client request or
its idle period, and its completion never marks the conversation pending. A
pending tool therefore survives every side request until the conversation's
own next request arrives, and the candidate keeps being pinged while the
command runs. Every other outcome behaves exactly as today. The log schema,
the outcome set, the proxy seam and the Nix service do not change.

## Acceptance criteria

| AC | Kind | Criterion | Measured by |
|----|------|-----------|-------------|
| AC1 | code | With a main request whose tool use is pending, an unmarked side request in the same conversation leaves the pending tool state and the request counter unchanged, and pings continue past the point where the current code ends the conversation `session_idle` | § Test seams cases 1, 2 and 4 in `tests/test_cache_keepalive.py`, each failing on the current code, under `just agent-workflow-tests`. Case 1 is the pending state and the pings past `session_idle`. Cases 2 and 4 are the counter, seen as a `tool_use` completion that stays current and a ping that is not superseded |
| AC2 | evidence | Issue-owner "long foreground command" cache deaths ≤ 30 over 7 days (127 in the 7 days to 2026-11-01) | `just agent-costs --days 7 --report cache` on mbp, run no sooner than 7 days after the first `just switch` that includes this change, so the whole window follows it. Post-merge evidence that cannot be met before merge (D5) |

Here "main request" is the issue's word for the subagent conversation's own
turn, its *thread request*, not the `main` outcome.

## Decisions

### Side requests (D1)

A side request is a request whose outcome is `no_tail_mark`: it has an agent
header, a strict JSON body, and no `cache_control` on any content block of its
last message. A body with no mark anywhere is one too. Claude Code's forks and
side queries look like this (#423 D5): agent summaries, hook prompts and
compaction run with `skipCacheWrite` or caching off. A
**thread request** is any other request that reaches a conversation record:
`main`, `unparsed`, `ttl_1h`, `thinking_budget` or `tracked`. Their handling
is unchanged. `main` stays a thread request of the main conversation, because
#423 D5 never parses a main body, so a main side query cannot be told from a
main turn.

### What a side request changes (D2)

For a side request, `observe`:

- finds or creates the conversation record, and builds the track as today:
  outcome, handle, `Accept-Encoding: identity` headers and the SSE tap;
- registers the track in the record's in-flight set with its send time;
- does **not** advance the request sequence, clear `pending_since`, stamp
  `last_request`, end a pinged idle period `resumed`, or reset its ping count.

At `started`, `_apply` keeps the candidate, as the `no_tail_mark` case already
does. At `done`, the track leaves the in-flight set and keeps its
`stop_reason` for its `request` log line, but `pending_since` is never set
from it (D3). Every thread request goes through `observe` exactly as today.

So for the conversation's own state machine (candidate, sequence, pending
tool, idle period, ceiling) a side request does not exist. For session
activity (#423 D8) it counts only by being in flight, the first condition.
After it is done it leaves nothing behind. This refines three #423 rules:

- **D5:** "every outcome other than `untracked` updates session activity"
  holds for a side request only while it is in flight.
- **D8:** a side request no longer counts toward "sent a client request after
  X's last touch".
- **D10:** the ceiling, `idle_s` and the eviction order count from the
  conversation's last thread request, and only a thread request ends an idle
  period `resumed`.

### Ordering (D3)

A side track holds no place in the conversation's request sequence: its
sequence is `None`, set once by `observe`, the one place that decides a
request is a side request. `_apply` never orders it, because its
`no_tail_mark` case returns before the D27 check. `_done` marks pending only
for a 2xx, `complete`, `tool_use` track whose sequence equals the record's
current sequence, so a side track never matches. Only thread requests move
the sequence, so #423 D27 now reads: candidate effects and the pending mark
are ordered among thread requests, and side requests never take part. The
overlapping cases, with today's result where it differs:

1. A side request is sent and finishes while thread request M is still
   streaming, then M completes with `tool_use`. M is still the newest thread
   request, so the conversation is pending. Today M is stale and never marks
   pending. This is the path of the 12,019 side requests sent while their
   thread request was in flight.
2. M completes with `tool_use`, then a side request is sent. Pending survives
   it and lasts until the next thread request. Today the side request clears
   it.
3. Thread request M1 completes with `tool_use` after a newer thread request M2
   was sent, with side requests in between. It is not pending, because M2
   moved the sequence. This is unchanged.
4. A delayed older `tracked` response arrives after a newer `ttl_1h` clear.
   It is still ignored. Side tracks never read or write `applied`. Unchanged.
5. A side request completes with `tool_use`. Nothing is marked pending. Today
   it marks pending when no request followed it.
6. A ping is in flight when a side request is sent. The ping's 2xx result
   moves the touch, because the candidate it refreshed is unchanged (#423
   D10: a ping's result applies to the candidate it was built from). A thread
   request still supersedes a ping in flight, as today. Today the side
   request supersedes the ping and the next tick pings again at once.
7. A side request reaches a conversation with no thread request yet. The
   record holds only that flight, and once it is done it is pruned as a fresh
   record is today, since a missing `last_request` counts as old.

### Accepted costs

- A subagent whose model runs with caching off sends only side requests. It
  is never pending and never a candidate, and only its flights count as
  activity for its siblings.
- `main` side queries still reset the main conversation's pending tool (D1).
- A pending tool now holds until the thread's next request, or for 60 minutes
  (#423 D8). The 60-minute ceiling counts from the last thread request and is
  no longer restarted by side requests. A wait killed mid-tool is pinged up to
  that bound, as #423 D17 already accepts.

### Docs

The `--keepalive` paragraph of `python/README.md` § `cache-proxy` gains the
side-request definition and its rule: it is activity only while in flight,
and it never clears or sets a pending tool, ends an idle period, restarts the
ceiling or supersedes a ping in flight. Its pending-tool, activity, ceiling,
`resumed` and supersession sentences then say "request" only of thread
requests. CLAUDE.md, AGENTS.md and `home/common/claude-code/README.md` do not
change.

## Test seams

Every case drives `Keepalive` directly through `KeepaliveCase` in
`tests/test_cache_keepalive.py` on its fake clock, with `tick` and `send`
against #422's fake upstream (#423 D12, D25). A side request is
`document(tail_mark=False, …)` from the conversation's own agent id, as the
existing `no_tail_mark` case builds it, and is placed where the log puts it:
about 9 s after the `tool_use`, or while the thread's response still streams.
Assertions read the pings sent and the `keepalive_end` lines. They never read
`_Conversation` fields (D4). The cases:

1. **AC1, the issue's demo.** It fails today. P's tracked request ends
   `tool_use`, and a side request (`end_turn`) completes 9 s later. The dues
   at 270, 540 and 810 s after P's send each ping P, where today the second
   due ends P `session_idle`. P's tool result, a tracked request, then ends
   the period `resumed` with 3 pings.
2. **Overlap.** It fails today. A side request is sent and completes while
   P's `tool_use` response still streams. P then completes, and two
   consecutive dues both ping P.
3. **Side request inside a pinged period.** It fails today. After one ping a
   side request completes and writes no `keepalive_end` line. P's next thread
   request ends the period `resumed` with every ping counted.
4. **Ping in flight.** It fails today. A side request is sent between a
   ping's build and its send. The ping's 2xx result moves the touch: no ping
   at the next tick, and the next ping is due 270 s after the ping's send.
5. **A finished side request leaves no activity.** It fails today. In each of
   two sessions a conversation ends `end_turn` and then gets a side request,
   ending `end_turn` in one and `tool_use` in the other. Both end
   `session_idle` at their first due, unpinged.
6. **A side request in flight is activity.** It pins today's behaviour. P
   ends `end_turn` and a side request stays in flight, so P is pinged at its
   due.

Every existing test stays as it is and keeps passing, D27's two
overlapping-request tests included. No proxy round-trip or command test is
added, because the seam, the request line's fields and the flag do not
change.

## Out of scope

- `main` side queries, which would need main bodies parsed (#423 D4, D5).
- `unparsed` requests and compressed bodies (#438). The log holds none.
- Treating a side request's own cache read as a touch. A fork may read the
  conversation's prefix, but whether that refreshes the candidate's entry is
  unmeasured.
- Any change to the outcome set, the log schema, `cache_proxy.py`, the Nix
  service, the 270 s due time, or the 60-minute windows.
- The AC2 measurement itself and `just switch`, which are the user's after
  merge.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A side request is exactly the `no_tail_mark` outcome (a body with no mark at all included); `main`, `unparsed`, `ttl_1h`, `thinking_budget` and `tracked` stay thread requests with today's handling | Issue: "requests that carry no cache mark"; #423 D5 (forks and side queries carry no tail mark; main bodies are never parsed; `unparsed` clears the candidate, #423 D23); mbp log: 17,094 `no_tail_mark`, 0 `unparsed` | Treating `main` requests as side ones too (a main body is never parsed, so a main side query cannot be told from a main turn); treating `unparsed` as side (it clears the candidate, so it needs D27's ordering, and compressed bodies are #438's) |
| D2 | A side request is session activity only while in flight: `observe` registers its flight and leaves the sequence, `pending_since` and `last_request` unchanged, and ends no idle period `resumed`; refines #423 D5, D8's third condition and D10's ceiling and `resumed` | Issue: "neither clear the pending tool state nor advance the request counter"; #423 D10/D11: the ceiling ("up to 60 minutes per idle conversation"), `idle_s` and the `resumed` period line measure the conversation's own idleness and tell paid-off pings from wasted ones; mbp log: 99.5% of side requests come while the thread is in flight or pending, and 24 `resumed` ends were triggered by a side request | Still stamping `last_request` (each side request restarts the ceiling and resets `idle_s` while the period's ping count runs on from before it); stamping it and still logging `resumed` (splits one wait into two "paid-off" periods and resets its ping count mid-wait) |
| D3 | A side track's sequence is `None`, set by `observe` alone; `_apply` never orders it and `_done` never marks pending from it, whatever its `stop_reason`; so a side request no longer supersedes a ping in flight, and D27's ordering runs among thread requests only | #423 D27 (pending only when nothing was sent since; effects ordered by sequence); #423 D10 (a ping applies to the candidate it was built from); mbp log: 78 side requests ended `tool_use`, 77 while the thread was already pending; the bar: one home per policy | Letting a side `tool_use` mark pending (a false pending holds the session active for up to 60 min, and a re-stamp stretches a true one); giving side tracks the current sequence and testing the outcome in `_done` (a second home for "which outcomes are side requests"); a second supersession counter (the candidate identity already settles it) |
| D4 | AC1 and D1–D3 are tested only through `KeepaliveCase` on the fake clock, with side requests placed where the log puts them (9 s after `tool_use`, or overlapping its stream), asserting pings and `keepalive_end` lines, never `_Conversation` fields; cases 1–5 fail on today's code | Issue AC1: a test in `tests/test_cache_keepalive.py` that fails on the current code; #423 D12, D25; the bar: assert observable behaviour, fail for one reason, shape fixtures like production | Asserting `epoch` or `pending_since` directly (private state; passes even if pings still stop); a proxy round-trip case (the seam and request-line fields are unchanged) |
| D5 | AC2 is post-merge evidence: the implementation delivers AC1, and AC2 is read from `just agent-costs --days 7 --report cache` on mbp no sooner than 7 days after the first `just switch` with this change, so the whole window follows it | Issue AC2; CLAUDE.md: switch only when asked; the cache report classifies deaths from transcripts (`long foreground command`) | Gating the merge on AC2 (no switched host has the change before merge); replaying the old proxy log as a substitute (the issue names the live report) |
