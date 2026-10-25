# Cache proxy: keepalive pings for idle subagent conversations — issue 423

Design for https://github.com/fagenorn/nix-config/issues/423. Base: `3f4c5072`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#422 Dn" cites
`2026-10-24-issue-422-cache-proxy-design.md`.

## Triage

Input signals: `contract_change=hit` (a new switch, and proxy-originated requests); `concurrency_or_persistence=hit` (a timer scheduler thread sharing state with the handlers); `open_design_questions=doubt` (identity, grouping, thinking handling and the switch are still open); `criteria_shape=hit` (two of the three criteria are live evidence).
Predicted paths: `python/agent_tools/cache_proxy.py`, `python/agent_tools/cache_keepalive.py`, `tests/test_cache_proxy.py`, `tests/test_cache_keepalive.py`, `python/README.md`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `justfile`, `docs/spikes/cache-proxy-keepalive.md`.
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`. Ran: full (shadow).

## Problem

A subagent's prompt-cache entry lives five minutes after its last use. Over 14
days a subagent conversation lost its entry about 2,646 times while it waited,
and each time paid a full cache write (1.25× input) to rebuild a prefix it had
built once already, about $2.5k at list price. Most were issue owners that ended
their turn and were woken by a child's hand-back after a median 12.6 minutes.
The rest waited on a long foreground command. A cache read costs 0.1×, and
#422's spike showed (fact 2) that replaying a conversation's request with
`max_tokens=1` and nothing else changed reads the whole entry and resets its
five-minute clock. The user wants the proxy that #422 put on the API path to
send those replays itself, only while the session is still doing something,
never to a main conversation (whose entries already last an hour), and behind
a switch so that the saving can be measured against the same pipeline with the
switch off.

Claude Code 2.1.302 has its own cache keepalive, but it does not cover this
case (D1). It is flag-gated (`tengu_sequential_cloud`, default off), and it
touches only the main loop's 1-hour subscriber entry, through the beta
`cache-keepalive-2026-09-03` and `POST /v1/messages/cache_touch`. No capture
in #422's spike or #429's re-test carried that beta.

## Solution

A new library module, `agent_tools.cache_keepalive`, holds the keepalive
state, its policy and its ping sender. `cache-proxy --keepalive` builds one
keepalive object and hands it to the server. The server reports every request
it forwards to that object, and the response's end as well. A scheduler thread
checks the state every 5 seconds. When a subagent conversation's five-minute
entry has gone 270 seconds without a touch, and the session still has
something going on, it replays the conversation's last request upstream with
`max_tokens=1` on a connection of its own. It logs the ping's usage and
discards the response. Without `--keepalive` the proxy is #422's pass-through,
byte for byte. The Nix service runs with the flag. The A/B evidence runs
start the built launcher by hand, once with the flag and once without (D3,
D13).

## Decisions

### Framework first (D1)

The keepalive is the issue's mechanism, a `max_tokens=1` replay. Fact 2
measured it on a five-minute entry, and the API documents that a cache hit
resets the entry's lifetime. Claude Code's built-in `cache_touch` keepalive is
not used, for three reasons: it is an undocumented beta, the client gates it to
the main loop's 1-hour subscriber entry, and nothing shows that it can refresh
a five-minute subagent entry. That gap is genuine, so the proxy fills it. The
built-in keepalive and its endpoint are recorded here so that a later issue can
measure them. This one does not.

### Interface and seam (D2, D3)

- **Module.** `agent_tools.cache_keepalive` is a library module, not a command
  and not a row of the command table. It exposes one class, `Keepalive`, built
  from the proxy's `LineLog`, a `connect` callable and a `clock`. `connect`
  opens a fresh connection to the proxy's configured upstream, using the same
  TLS context as client traffic. `clock` returns monotonic seconds. The proxy
  passes `time.monotonic` as the clock, and tests pass a fake one. Nothing
  runs at import time.
- **Per-request seam.** For each request the server is about to send
  upstream, after any other transform the proxy applies (#429's reorder
  included), the handler calls `observe(method, path, headers, body)`. That
  call returns a track. The track carries the request's `outcome` (D5) and
  its conversation handle (D11), and gives the headers to send (D9). It then
  takes `started(status)` when the response headers arrive, each response
  chunk the relay writes, and one final `done(relay_outcome)`. An upstream
  failure before any response calls only `done`. A request leaves flight
  exactly once, whatever its outcome, so `done` is called on every path
  (D19). The keepalive reads only the bytes and headers the proxy actually
  forwards, so that its replay matches what upstream cached. Classification
  parses a subagent body before it is sent. That costs about 2.5 ms for a
  0.94 MB body on mbp, which is small next to upstream's time to first byte.
- **Scheduling seam.** `tick()` reads the clock, applies the stop rules (D10)
  and returns the pings now due, each one a fully built request. `send(ping)`
  sends a ping and records its result. `run(stop)` is the production loop: it
  calls `tick()` every 5 seconds and starts one daemon thread per due ping that
  calls `send`. Only the command's `main` starts `run`. Tests call `tick` and
  `send` themselves.
- **Failure posture (D18).** A keepalive bug must never block client traffic.
  An exception that escapes `observe`, a track call, `tick` or `send` is caught
  at the seam and written as one `keepalive_error` line, with `stage` and
  `error` (the exception's class and message). The rest of that request
  runs as an `untracked` one would, and the scheduler loop keeps running. The
  outcome dispatch still raises on an unknown value, and the seam is where that
  error is recorded.
- **Switch (D3).** `cache-proxy --port N [--upstream URL] [--keepalive]`.
  Without the flag the server gets no keepalive object, no scheduler thread
  runs, headers are forwarded exactly as #422 forwards them, and every log line
  is unchanged. With the flag, the `listening` line gains `"keepalive":true`
  and request lines gain the D11 fields. In the claude-code module,
  `cacheProxyArgs` gains `--keepalive`, so both hosts' services run with it
  once the user activates them. Turning it off means dropping the flag and
  rebuilding.

### Conversation identity and eligibility (D4, D5)

A **session** is the value of the request's `X-Claude-Code-Session-Id`
header, which Claude Code sets once for the whole session, so its subagents
share it. A **conversation** is the pair of that value and the value of
`x-claude-code-agent-id`. Claude Code sets the agent header from the agent
context of every non-main agent and never sets it for the main loop. The
pair's **candidate** is the most recent request that may be replayed for that
conversation.

`observe` classifies each request into one outcome from a closed set. It
checks in this order and stops at the first match:

1. `untracked`: the method is not `POST`, the path (without its query) is not
   `/v1/messages`, or there is no session header. The keepalive ignores the
   request completely.
2. `main`: no agent header. The body is never parsed. The request counts only
   toward session activity (D8).
3. `unparsed`: the request carries a `Content-Encoding` header, or its body
   is not a JSON object under the strict `agent_tools.canonical` hooks.
4. `no_tail_mark`: the last message carries no `cache_control` on any of its
   content blocks. Claude Code's forks and side queries look like this:
   agent summaries, hook prompts and compaction run with `skipCacheWrite`,
   which its marker audit names `fork_tail_skip_cache_write`, or with caching
   off. The candidate is kept, because such a request writes no conversation
   entry.
5. `ttl_1h`: some mark has `ttl` `"1h"`. Marks are the `cache_control`
   objects of `tools[i]`, `system[j]`, `messages[i].content[j]` and a block's
   inner `content[k]`, plus a top-level one, the same set #429 counts (D16).
   A mark without a `ttl`, or with `"5m"`, is five minutes. The candidate is
   cleared.
6. `thinking_budget`: `thinking.type` is `"enabled"`. That form requires
   `budget_tokens` at least 1,024 and below `max_tokens`, so a `max_tokens=1`
   replay would be rejected. Lowering the budget, or changing thinking, would
   invalidate the message cache. The candidate is cleared.
7. `tracked`: everything else. This request becomes the candidate.

An effect on the candidate (replace, clear or keep) applies at `started`,
and only when the status is 2xx (D19). A request that failed upstream may
never have touched the cache. An entry is readable once its response starts
streaming (#429 D14), so a long generation is already the candidate while it
streams. Every outcome other than `untracked` updates session activity,
whatever the status. Dispatch on the outcome fails loudly on a value outside
the set. Main-session bodies and untracked bodies are never parsed, and only
a candidate's body and headers are kept.

### The ping (D6, D7)

- **Body.** The candidate's body is parsed strictly, `max_tokens` is set to
  `1`, and the result is encoded as compact ASCII JSON
  (`separators=(",", ":")`, `ensure_ascii=True`), keeping key order (D20).
  A lone surrogate escape, which a truncated tool output can carry, then stays
  an escape and does not fail the UTF-8 encode. Every other field keeps its
  value, including `stream`, `thinking`,
  `output_config`, `context_management`, `metadata` and every `cache_control`.
  The tokens the API caches are the same as in the original request, and the
  encoding is not part of the cache key.
- **Request.** The method and path, including the query, are the candidate's.
  Its end-to-end headers keep their names, order and duplicates: the session
  and agent headers, `authorization`, `anthropic-beta`, `anthropic-version`,
  `x-app`, `user-agent` and the `x-stainless-*` headers. Only three things
  change: `Host` becomes the upstream host, `Content-Length` is recomputed, and
  `Accept-Encoding` becomes `identity` (D9). Hop-by-hop headers are dropped, as
  #422 D6 drops them. No header of the proxy's own is added.
- **Transport.** A ping travels on a fresh upstream connection and never uses
  a client connection. It has a 30-second timeout and is never retried (#422
  D6). Its response is read to the end, and its usage is taken from the
  `message_start` and `message_delta` events, or from a JSON body's `usage`.
  The response is then discarded. No byte of it reaches a client, by
  construction.
- **Credentials (D7).** This changes #422's "the proxy holds no credential".
  The keepalive keeps each candidate's request headers, `authorization`
  included, in process memory only, from the request's 2xx response start
  until the candidate is cleared, replaced or ended. They are never logged,
  persisted or sent anywhere but the configured upstream. A 401 or any other
  non-2xx answer to a ping ends the candidate, so an expired token costs one
  refused request.

### Session activity (D8, D9)

A session is **active** for candidate X at time t when some conversation of
X's session (its main conversation, X itself or another subagent) meets one of
these conditions:

- it is **in flight**: a request it sent upstream less than 60 minutes ago
  has not called `done` (the bound keeps a lost `done` from holding a session
  active forever);
- it is **pending a tool**: its last 2xx response completed with `stop_reason`
  `tool_use`, less than 60 minutes ago, and it has sent no request since then,
  so a tool is running and its result will come back;
- it **sent a client request after X's last touch** (D10).

Pings never count as activity, so two idle conversations cannot keep each
other alive. A candidate idle 270 seconds past its last touch counts toward
its own activity only through the first two conditions, which is right: a
subagent waiting on its own long foreground command is mid-turn and will
resume. This reading of the issue's "other conversation still active" covers
both the cases it names. Children running show up as in flight, pending or
recent requests. Commands being polled show up as recent requests, and a long
foreground command shows up as pending. It also covers the AC2 wait, in which
nothing at all is requested for eight minutes.

**Response tap (D9).** Pending-tool needs each observed response's final
`stop_reason`. A request whose outcome is not `untracked` is forwarded with
`Accept-Encoding: identity`, which the spike harness and #429's re-test
already used to read usage. The server may always answer uncompressed. The
relay feeds that request's response chunks to an incremental SSE reader. The
reader keeps the `stop_reason` of a `message_delta` event, splitting lines
across chunk boundaries and decoding only `message_*` events. A response with
any other `Content-Type` or `Content-Encoding`, or a relay outcome other than
`complete`, has no `stop_reason`, so it is not pending. The response bytes
the client gets are unchanged.

### Timing and stop rules (D10)

- **Touch.** A conversation's **last touch** is the upstream send time of
  either its last client request whose response started 2xx with outcome
  `tracked`, or of its last ping that got a 2xx. The send time is used, not
  the response's end, because the entry's five minutes start when the prompt
  is processed. A long
  generation is therefore pinged while it is still in flight, which keeps that
  entry for the next turn.
- **Due.** A ping is due when 270 seconds have passed since the last touch.
  That leaves 30 seconds for the 5-second tick and the ping's own
  time-to-first-byte. The 270-second figure is the issue's, and fact 2's
  210-second replay sits inside it.
- **At due**, in this order:
  1. if 60 minutes have passed since the conversation's last *client* request,
     it ends with `ceiling`;
  2. if the session is not active (D8), it ends with `session_idle`;
  3. otherwise a ping is built and sent.

  A ping that answers 2xx becomes the new touch. Any other result, a timeout
  or a connection failure ends the conversation with `ping_failed`.
- **End.** An ended conversation is never pinged again until a new client
  request makes it a candidate again. A client request that arrives after one
  or more pings in the current idle period ends that period with `resumed`.
- **Bounds.** At most 64 candidates are held. A 65th evicts the candidate
  whose last client request is oldest, with `evicted`. Activity records older
  than 60 minutes that are not in flight are pruned. A conversation has at
  most one ping in flight, and a ping's result applies only to the candidate
  it was built from. A newer client request supersedes it.
- **Restarts.** State lives in memory. After a proxy restart, a conversation
  is unknown until its next request.

The issue's rule pings a subagent that has finished for good for as long as
the rest of the session stays active, up to the 60-minute ceiling, because the
proxy cannot tell "done" from "waiting to be woken". For example, a
`SendMessage` can resume any finished agent. The same holds when the only
activity is a tool that is waiting on a permission answer, or one left
pending by a process killed mid-tool. That cost is accepted, bounded by the
ceiling and measured (D15, D17, D22).

### Log contract (D11)

These are additions to #422 D8/D16, written only with `--keepalive`:

- **`request` lines** gain `keepalive` with the D5 outcome. Unless the outcome
  is `untracked`, they also gain `conversation`, the handle, and `stop_reason`
  when the tap saw one. A request rejected before its body was read (`411`,
  `400`) carries none of them (#429 D15). The handle is the first 12 hex
  digits after `sha256:` in the digest that
  `agent_tools.canonical.telemetry_digest` gives for
  `{"agent": <agent header or null>, "session": <session header>}`. It is a
  short stable handle and never the header value.
- **`ping` lines** carry `conversation`, `model` (from the body), `idle_s`
  (seconds since the conversation's last client request), `status`, `ttfb_ms`,
  `duration_ms` and `outcome` (`complete` or `upstream_error`). They also
  carry `usage`, the response's `input_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`
  and `cache_creation` split, plus `error` and up to 4 KiB of an error body on
  a status of 400 or more, as #422 D8 allows.
- **`keepalive_end` lines** carry `conversation`, `reason` (`resumed`,
  `ceiling`, `session_idle`, `ping_failed` or `evicted`), `pings` (the count in
  this idle period) and `idle_s`. A `resumed` period with no ping writes no
  line, because that is every ordinary turn.
- **`keepalive_error` lines** carry `stage` (`observe`, `track`, `tick` or
  `send`) and `error` (D18).

### Docs

`python/README.md` § `cache-proxy` gains `--keepalive`: eligibility, activity,
timing, the ping's shape, the held credentials and the new log fields. The
claude-code README's § Cache proxy gains several points: the service runs with
the keepalive, how to switch it off, how an A/B pair runs, and the accepted
cost of pinging finished subagents. Its sentence "It forwards requests
unchanged today" is replaced. The evidence for AC2 and AC3 is a point-in-time
report, `docs/spikes/cache-proxy-keepalive.md`, which the PR links. CLAUDE.md
and AGENTS.md do not change, so the instruction budget is untouched.

### Live evidence (D13–D15)

- **Venue (D13).** The evidence runs on mbp against the built, unactivated
  outputs (#422 D14). No agent runs `just switch`. Each arm starts the built
  `cache-proxy` launcher in the foreground under `launch-scope exec`, with the
  service's `SSL_CERT_FILE`, `--port 0` (the port is read from the `listening`
  line) and `--keepalive` in the on arm only. The proxy log goes to a file of
  the arm's own. The session under test is started through the built `claude`
  wrapper with a caller-set `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>` and
  `ENABLE_TOOL_SEARCH=true`, which the wrapper leaves alone (#422 D10 rule 2).
  Only that session's process tree reaches the ad-hoc proxy, and the arms do
  not depend on whether port 27183 is served. Every `claude -p` under test
  sets `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`, so its transcripts are
  written (#429 D19). Each arm's log must contain at least one `request` line
  for `/v1/messages`. The on arm's lines must carry `keepalive`, and the off
  arm's must not.
- **AC2, keepalive works (D14).** The arms run in order: off, then on. Each is
  one fresh scripted `claude -p` session from a new scratch directory. The
  main session dispatches a subagent P. P first reads a generated file that
  carries a nonce unique to the arm, sized so that P's own context exceeds 60%
  of its context at the wait. A cache entry shared with other sessions, such as
  the system prompt, therefore cannot keep the off arm's rewrite under 50%. P
  then dispatches a child C and waits on it. The issue's background form is
  used if `claude -p` keeps the process alive for it; otherwise P waits on a
  foreground call. C's only work is one foreground `sleep 480`, with a Bash
  timeout above that. P's first call after C returns is the measured call.
  - Its ratio is `cache_creation_input_tokens` over its predecessor's context
    (`input + cache_read + cache_creation`), taken from P's transcript as the
    cache report defines a call. The thresholds are a ratio under 0.10 with the
    keepalive on and over 0.50 with it off. The gap between the two calls must
    be at least 480 s.
  - The cache report (`just agent-costs --report cache`) runs over an
    isolated copy of each arm's session transcripts, with an events window that
    holds only the measured call. It must show that call as a death for P's
    agent type in the off arm and none in the on arm.
  - The on arm's proxy log must show at least one `ping` line for P's
    conversation, with outcome `complete` and `cache_read_input_tokens` above
    0.
- **AC3, no regression (D15).** `just evals from-issue 1` runs once per arm,
  on first, and the arms are otherwise identical. The on run must print
  `VERDICT: PASS`. An arm's cost is the claude stratum's `totals.cost_usd`
  (`cost_basis` `list-price`) from `just agent-costs --format json --days 0
  --projects-dir <copy>`, run over an isolated copy of that eval's own
  transcripts: every root transcript whose `cwd` is the sandbox repo or lies
  under it, together with its subagent directory (#429 D19). The on arm also
  adds its pings' list-price cost. Pings never reach a transcript. Each `ping`
  line's `usage` is priced with `agent_costs.PRICING`, `model_family` and
  `cache_write_split`, which is the one home of prices. The threshold is on
  total < off total. Both `results.jsonl` lines are cited, together with each
  arm's ping count, outcomes and cost, and its `keepalive_end` reasons
  (D21).
- **Conditions.** Every run is one trial and is never repeated to pass (#422
  D27). Each run takes its cutoff from the controller's `deadline_at` (#422
  D20, D24). A run that would pass the cutoff is recorded `human-pending` with
  its exact command. A threshold that is missed is reported with its numbers,
  and the issue stays open for the user.

## Test seams

Every new test runs under `just agent-workflow-tests`, through a new
`tests/test_cache_keepalive.py` in the recipe's list next to
`tests/test_cache_proxy.py`. The tests reuse #422's fake loopback upstream and
recording log stream (#422 D15) rather than adding a second fake. Nothing
mocks `http.client`, and assertions are made on the bytes the fake upstream
received and the JSON lines the log recorded (D12).

- **Keepalive, driven directly with a fake clock (AC1).** Request and
  response events go in through `observe` and the track's chunk and `done`
  calls. Response chunks are SSE shaped like Claude Code's: `message_start`,
  content deltas, then `message_delta` carrying `stop_reason`. Request bodies
  are shaped like the captured ones: an adaptive-thinking subagent body whose
  marks carry no `ttl` and whose last mark sits on a trailing `system`-role
  message, a main body with `ttl` `"1h"` marks, and their headers. `tick` and
  `send` run against the fake upstream. The cases:
  - a tracked conversation, 270 s after its touch with a sibling in flight,
    gets exactly one ping. Upstream receives the same method and path. The JSON
    body equals the original except `max_tokens` is `1`. The headers equal the
    original's in order except for `Host`, `Content-Length` and
    `Accept-Encoding: identity`;
  - no ping is sent before 270 s;
  - at due with the session inactive the conversation ends `session_idle`, and
    later activity elsewhere does not revive it;
  - pings repeat while the session stays active. None is sent once 60 minutes
    have passed since the last client request (`ceiling`);
  - a session whose only activity is the candidate's own pending tool
    (`stop_reason` `tool_use`) keeps it pinged, while `end_turn` does not;
  - two idle conversations' pings do not keep each other alive;
  - a `ttl_1h` subagent, a main conversation and a `thinking_budget`
    conversation are never pinged, while a `no_tail_mark` request leaves the
    earlier candidate pinged;
  - a non-2xx client response changes no candidate;
  - a 4xx ping ends the conversation `ping_failed`, with its error body logged,
    and nothing is retried;
  - a client request after a ping ends the period `resumed`, with its count;
  - a client request that arrives while a ping is in flight supersedes it, and
    the ping's answer moves no touch;
  - a candidate whose response has started 2xx but not finished is pinged at
    its due time;
  - a body carrying a lone surrogate escape gets a ping whose body is the same
    JSON value;
  - the 65th candidate evicts the oldest.
- **Through the proxy, in process.** A `ProxyServer` with a fake-clocked
  keepalive is placed in front of the fake upstream. A client request to it
  arrives upstream with `Accept-Encoding: identity`, and its response reaches
  the client unchanged. After the clock advances and `tick` and `send` run,
  upstream has received the ping, and the client's idle connection receives no
  further byte. The request line carries `keepalive`, `conversation` and
  `stop_reason`. A keepalive whose `observe` raises still lets the request
  through unchanged, and the log gets one `keepalive_error` line. With no
  keepalive object, #422's existing tests keep proving that the forwarding is
  verbatim.
- **Command.** `python -m agent_tools.cache_proxy --port 0 --keepalive
  --upstream …` writes a `listening` line with `"keepalive":true`. `--help`
  lists the flag, and the launcher test keeps passing.

## Acceptance mapping

| AC | Measured by |
|----|-------------|
| 1 [code] scheduler behaviour | § Test seams, keepalive and proxy cases, in `just agent-workflow-tests` |
| 2 [evidence] keepalive works | D14 on mbp, recorded in `docs/spikes/cache-proxy-keepalive.md` |
| 3 [evidence] no regression | D15 on mbp, same report |

## Out of scope

- TTL rewriting of any kind, and the start-up prefix reorder (#429).
- Claude Code's built-in `cache_touch` keepalive, and any keepalive for
  main-session (1-hour) entries (D1).
- Telling a finished subagent from a waiting one, for example by parsing
  parents' tool results (D17).
- Compressed request bodies (#438). They classify as `unparsed`. If #438
  turns them on, it extends observation.
- Changing the wrapper's routing default, which #438 owns.
- State that survives a proxy restart, and pings through any other upstream.
- Teaching `agent-costs` to read proxy logs. The evidence prices pings
  itself (D15).
- `just switch` and the user's demo after activation.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The keepalive is a proxy-sent `max_tokens=1` replay of the conversation's last request. Claude Code's own keepalive (flag `tengu_sequential_cloud`, beta `cache-keepalive-2026-09-03`, `POST /v1/messages/cache_touch` by request id) is not used, and is recorded for a later measurement | Issue: "replays its last request with `max_tokens=1`"; spike fact 2; the 2.1.302 binary gates its keepalive to the main loop's `ttl==="1h"` subscriber entry, flag default off, absent from every spike capture; the bar's framework-first rule (gap raised here, not built around silently) | Calling `cache_touch` for subagent entries (undocumented beta, no evidence that it refreshes 5-minute entries, the issue fixes the mechanism); waiting for Claude Code to cover subagents (leaves the measured leak open) |
| D2 | `agent_tools.cache_keepalive` is a library module with one `Keepalive(log, connect, clock)` object. The server calls `observe` on the bytes and headers it forwards, after any other transform, and the track takes the chunks and one `done` on every path; `tick` and `send` are split from the `run` loop, which only `main` starts | Concurrency note: #429 edits `cache_proxy.py` too, so the seam must stay narrow; the bar: single responsibility, tests that can fail (an injected clock instead of sleeping); agent-helpers rule 2 | Keepalive logic inside `ProxyHandler` (merge conflicts with #429, untestable without real time); a separate keepalive process tailing the proxy log (the log holds no bodies or credentials, by #422 D8) |
| D3 | The switch is `cache-proxy --keepalive`. Without it, behaviour and logs are #422's byte for byte and no thread runs. The Nix `cacheProxyArgs` gains the flag, so the service runs with it, and off means dropping the flag and rebuilding | Issue: "switchable for A/B"; "no shadow phase"; #429's `--reorder` shape; DRY: the port and args have one Nix home (#422 D5) | An environment variable or a runtime toggle endpoint (a second home, and a reserved path #422 D5 does not have); shipping the service off (the issue's rollout gate is the A/B, not a shadow phase) |
| D4 | Session = `X-Claude-Code-Session-Id`, conversation = (session, `x-claude-code-agent-id`), candidate = that conversation's latest 2xx `tracked` request. No session header means untracked, and no agent header means main: activity only, body never parsed, never pinged | Spike request log: the session header is on every request, the agent header on subagent requests only; the 2.1.302 source sets it from each non-main agent context; issue: main-session conversations are never pinged | A digest of system+tools+first message (siblings with identical prompts collide, since the billing suffix is content-derived and was equal in #429's re-test; compaction or a tool change strands the old key, which then gets pinged for an hour); the agent header alone without the tail-mark gate (D5: agent summaries share the agent id) |
| D5 | Closed outcome set, checked in order: `untracked`, `main`, `unparsed` (any `Content-Encoding`, or not a strict JSON object), `no_tail_mark` (keeps the candidate), `ttl_1h` (any 1h mark; clears it), `thinking_budget` (`thinking.type` `"enabled"`; clears it), `tracked` (replaces it). Candidate effects apply only on 2xx, and dispatch fails loud on an unknown value | The 2.1.302 source: forks and side queries run with `skipCacheWrite` or caching off, so they have no tail mark; captured bodies: adaptive thinking, 5m subagent marks, 1h main marks; the thinking API needs `budget_tokens` ≥ 1024 and < `max_tokens`; a failed request may not have touched the cache; the bar's fail-loud rule | Pinging the `enabled` form with a budget-sized `max_tokens` (pays for thinking output on every ping); disabling thinking on the ping (invalidates the message cache); letting a side query replace the candidate (it would refresh the wrong prefix) |
| D6 | The ping body is the candidate parsed strictly, with `max_tokens=1`, compact UTF-8 and key order kept, every other field unchanged, `stream` included. Same method and path; the candidate's headers in order, with `Host`, `Content-Length` and `Accept-Encoding: identity` the only changes; a fresh connection, a 30 s timeout, no retry; the response is read for usage and discarded | Spike fact 2 changed only `max_tokens`; #422 D6 (no proxy-added headers, no retries); the cache key is the tokens, not the JSON bytes; #429 D10 uses the same encoding | Byte-level substitution of `max_tokens` (also matches nested tool inputs that carry that key); `stream:false` for an easier parse (an untested change to a proven replay); reusing a client's keep-alive upstream connection (a ping could interleave with that client's next request) |
| D7 | The keepalive keeps each candidate's request headers, `authorization` included, in process memory only, until the candidate is cleared, replaced or ended; they are never logged or persisted. Any non-2xx answer to a ping, a 401 included, ends the candidate | A replay needs the conversation's own credential and betas; #429's re-test captures show subagent requests omitting `extended-cache-ttl-2025-04-11`, which main requests carry; the bar: defense in depth (loopback bind kept, the upstream fixed); #422 D2 kept captured bearers in memory only | Taking the session's newest request's headers (main and subagent betas can differ, which could change cache behaviour); reading the keychain (a second credential path, GUI-prompt risk, #422 D2) |
| D8 | A session is active for X when any of its conversations, the main one and X included, is in flight (sent under 60 min ago), pending a tool (last 2xx complete response `stop_reason` `tool_use`, under 60 min old, nothing sent since), or sent a client request after X's last touch. Pings never count as activity | Issue: ping "while any other conversation in the same session is still active (children running, commands polled) … stops when the whole session is idle"; the leak's second cause is long foreground commands; AC2's 8-minute wait sends nothing | Request recency only (a lone long foreground command, and AC2's wait itself, would read as idle); counting pings (idle conversations would keep each other alive for the full ceiling) |
| D9 | A request whose outcome is not `untracked` is forwarded with `Accept-Encoding: identity`, and the relay feeds its response to an incremental SSE reader for `message_delta.stop_reason`. Any other content type or encoding, or an incomplete relay, means no stop reason | Pending-tool (D8) needs the stop reason; the spike harness and #429's re-test forced identity on the upstream leg to read usage; a server may always answer uncompressed; stdlib Python 3.13 has no zstd or brotli | Decompressing a copy for the tap (partial: no br or zstd in the stdlib); a tap that silently goes blind when upstream compresses |
| D10 | Last touch = the upstream send time of the last 2xx `tracked` request or 2xx ping. Due at 270 s, checked every 5 s. At due: a 60-min ceiling since the last client request (`ceiling`), then session idle (`session_idle`), else ping. A failed ping ends with `ping_failed`, a client request after pings ends with `resumed`; 64 candidates at most (`evicted`); one ping in flight per conversation, applied only to its own candidate; one daemon thread per ping; in-memory only | Issue: "idle about 270 seconds", "up to 60 minutes per idle conversation", "stops when the whole session is idle"; the cache lifetime counts from prompt processing; the Claude Code keepalive's own 60-min activity window | Measuring idle from the response's end (a long generation's entry dies before its first ping); a serial ping loop (many conversations due together can overrun the 30 s margin); no candidate cap (unbounded memory in a long-running service) |
| D11 | With `--keepalive`, `request` lines gain `keepalive`, `conversation` and `stop_reason`; new `ping` lines (usage, model, idle, status, timing, error body ≤ 4 KiB) and `keepalive_end` lines (reason, pings, idle); the handle is 12 hex digits of `telemetry_digest({"agent","session"})` | #422 D8 and D16 (structured fields, never header values); the bar: the log stream is the debugger, short stable handles; agent-helpers rule 4 (one digest home); AC3 must price pings that no transcript records | Raw session or agent ids in the log (header values, #422 D8); no per-period end line (pings that paid off could not be told from wasted ones) |
| D12 | AC1 is tested by driving `Keepalive` directly with a fake clock and SSE- and body-shaped fixtures like the captures, `tick`/`send` against #422's fake loopback upstream, one in-process proxy round trip, and the `--keepalive` command line. Nothing mocks `http.client` | AC1: "unit tests with a fake upstream and a fake clock"; #422 D15; the bar: assert observable bytes and lines, shape fixtures like production | Sleeping real seconds (a 270 s test); mocking the connection (a call assertion survives any implementation) |
| D13 | Evidence arms run the built launcher ad hoc in the foreground on a free loopback port (`--port 0`), flag on or off as the only difference, each with its own log. The session goes through the built wrapper with a caller-set `ANTHROPIC_BASE_URL` and `ENABLE_TOOL_SEARCH=true`; no switch, and not port 27183 | CLAUDE.md: switch only when asked; #422 D14; the wrapper leaves a caller-set non-proxy URL alone (#422 D10); mbp has no service on 27183, and other agents' sessions launched meanwhile would route into a proxy on 27183, which #429 D18's in-flight evidence also binds | A foreground proxy on 27183 (#429 D18's choice; here other sessions' traffic would pollute the arm's log and its activity rule, and it collides with #429's runs and with an activated service); `just switch` (the user's, not the agent's) |
| D14 | AC2: off then on, each a fresh `claude -p` session. Subagent P reads a per-arm nonce file large enough that over 60% of its context is its own, dispatches child C (background if `-p` allows it, else foreground), and C runs one foreground `sleep 480`. Measured: P's first post-wait call's creation ÷ the predecessor's context (< 0.10 on, > 0.50 off, gap ≥ 480 s); the cache report's death row in a window holding only that call; at least one `complete` ping for P in the on arm | Issue AC2 and demo; the cache report's call and death definitions (#421); account-wide sharing of the system-prompt entry could hide an off-arm death unless P's own prefix dominates | A child that polls in a loop (shapes the evidence around the activity rule instead of the issue's wait); measuring on the main session (1h TTL, never pinged) |
| D15 | AC3: `just evals from-issue 1` once per arm, on first. Cost = the transcripts' list price from `agent-costs --format json --days 0 --projects-dir` over an isolated copy of the eval's own transcripts, plus, in the on arm, every ping line priced with `agent_costs` pricing; threshold on < off; one trial, never repeated; deadline cutoff → `human-pending`; a miss is reported, never retried | Issue AC3; #429 D12 and D19's cost basis; transcripts never record pings, so omitting them biases toward on; #422 D20, D24 and D27 | Transcript cost alone (understates the on arm by its pings); repeated trials until on wins (#422 D27) |
| D16 | Mark enumeration (D5) and the compact body encoding (D6) follow #429 D10 and D16 exactly. Whichever of #423 and #429 merges second points its copy at the first one's function in the same PR, so each has one home | The bar: DRY for knowledge that must change together; #429 is in flight in another worktree, and its concurrency note keeps the modules separate until one lands | A shared module created now (couples two in-flight branches through a third file); two permanent copies (they must change together) |
| D17 | The issue's stop rule is applied as written: a subagent that will never resume is pinged while the session stays active, up to the ceiling. The waste is accepted and measured by AC3 and the `keepalive_end` lines; no completion heuristic is built | Issue decisions: "ping while the session has other active conversations; hard ceiling 60 min"; any finished agent can be resumed by `SendMessage`; pinging is net positive while a resume comes within about 11 pings | Parsing a parent's `Agent` tool results to retire finished children (couples the proxy to tool-result prose); a ceiling shorter than the issue's 60 min (contradicts the issue's decision) |
| D18 | A keepalive exception never blocks client traffic: one escaping `observe`, a track call, `tick` or `send` is caught at the seam and written as one `keepalive_error` line (`stage`, `error`), the request is forwarded as an `untracked` one would be, and the loop keeps running; in-flight state is bounded by the 60-min ceiling, so a lost `done` cannot pin a session active | #422's posture that a dead proxy never stops work; #429 D13 (forward the original bytes, log the error before absorbing it); the bar: log the original error before a swallow | Letting the handler fail (a keepalive bug would break every routed session); a silent catch (hides the bug) |
| D19 | Refines D2, D5 and D10: the track takes `started(status)` at the response headers, the chunks, then `done(relay_outcome)` (only `done` after a pre-response failure). Candidate effects and the touch apply at `started` with a 2xx status, and a subagent body is classified in `observe`, before the send | #429 D14: an entry is readable once its response starts streaming; a generation longer than 270 s must already be the candidate; measured on mbp: `json.loads` of a 0.94 MB body takes 2.5 ms, against an upstream time to first byte of seconds (#422 D27) | Applying effects at `done` (a long generation's entry expires unpinged); classifying after the response (keeps the latency path free, but loses the in-flight case for a 2.5 ms saving) |
| D20 | Refines D6 and narrows D16 to marks: the ping body is compact ASCII JSON (`ensure_ascii=True`), keeping key order | Measured: Python decodes a lone surrogate escape into a `str` that `ensure_ascii=False` output then cannot encode as UTF-8 (`UnicodeEncodeError`), and Claude Code's JSON can carry one from a truncated tool output; the escape decodes to the same string upstream, so the cached tokens are unchanged | #429's `ensure_ascii=False` (a ping for such a conversation would fail at build); `surrogatepass` (sends invalid UTF-8 upstream) |
| D21 | Refines D15: the AC3 report gives, per arm, the ping count, the ping outcomes and their cost, and the `keepalive_end` reasons beside the eval costs. The result is reported as observed, never re-run | `results.jsonl`: recent `from-issue 1` runs took 256–322 s, so few conversations reach a due time and run-to-run variance may exceed the pings' effect; the bar: truthful terminal states | Lengthening the eval or adding trials (changes the issue's AC3); omitting the ping breakdown (a cost difference could not be attributed) |
| D22 | Refines D17: the first lever, if AC3 or the `keepalive_end` reasons show pings to conversations that never resume outweighing the saves, is to ping an ended-turn conversation only while one of its own children is active, through the `x-claude-code-parent-agent-id` header that Claude Code 2.1.302 sends. It is recorded and not built | Break-even: a resume saves about 1.15× the prefix and each ping costs 0.1×, so the full 13-ping ceiling period loses 1.3× when no resume follows; the issue's explicit stop rule is session-wide | Building the children rule now (narrows the issue's stated decision, and it would miss wakes from background-command notifications) |
| D23 | Fills the effect D5 left open: `unparsed` clears the candidate when its response starts 2xx, as `ttl_1h` and `thinking_budget` do | The conversation has moved past the candidate's prefix in a way the keepalive cannot read, so a ping would refresh a superseded entry while holding a credential (D7); observing compressed bodies is #438's | Keeping the candidate (pings on a stale prefix, a credential held longer); replacing it with the raw bytes (an unparsed body cannot be rebuilt with `max_tokens=1`) |
| D24 | Refines D2, D18 and D19: `started(status, content_type, content_encoding)`; `chunk(data)` after each client write; a `resumed` end keeps the candidate and every other `keepalive_end` reason clears it; with `--keepalive` a request line carries its track's `log_fields()`, or `"keepalive":"untracked"` alone once `observe` or a track call raised; an unexpected exception in `send` ends the conversation `ping_failed`, then propagates; `connect(timeout)` returns an unconnected connection from `cache_proxy.open_upstream` with a context from `cache_proxy.upstream_tls`, which client traffic also uses; `cache_keepalive` imports the transport constants from `cache_proxy`, which imports `cache_keepalive` only inside `main` | The tap needs the response's type and encoding (D9); D18's "as an untracked one would"; a stranded in-flight ping would hold a credential that no stop rule reaches; the bar: one home for the failure set and the 4 KiB limit; a top-level import both ways is a cycle | `started(status)` alone (a blind tap); a second copy of `UPSTREAM_FAILURES`; no keepalive field after an error (the line would read as a pre-flag one) |
| D25 | Every new test lives in `tests/test_cache_keepalive.py`, which imports `FakeUpstream`, `RecordingStream`, `json_reply`, `closed_port` and `TIMEOUT` (no `TestCase` class) from `tests.test_cache_proxy`; that file is not edited; the `run` loop is tested with `cache_keepalive.TICK_INTERVAL` patched small | #429 edits `tests/test_cache_proxy.py`; `tests/test_review_history.py` already imports from a sibling test module; D12 (one fake, nothing mocks `http.client`); the bar: tests that can fail, without real-time sleeps | New cases in `tests/test_cache_proxy.py` (conflicts with #429); a copied fake; 5 s real ticks |
| D26 | Refines D13–D15: P waits on C in the foreground and the background form is not probed; P reads six generated 48,000-byte nonce files; every session runs `-p --model sonnet --dangerously-skip-permissions --output-format json`, as `run-eval.sh` does; P's handle comes from its transcript's `sessionId` and `agentId`; both eval arms set `EVAL_TIMEOUT=900`; the cutoff is `deadline_at` − 60 min, with 15 min left for an AC2 arm and 20 min for an eval arm; an AC2 arm is void only for Task 4's closed reasons (a gap under 480 s and P's own share under 60 % among them), and a void arm reruns once with a new nonce, while a missed threshold is never rerun | D14 allows the foreground form, which yields the same measured call without another live run before the deadline; the Read tool's 25k-token limit per call; the eval runner's flags; transcripts carry `sessionId` and `agentId` on every record; recent `from-issue 1` runs took 256–322 s; #422 D20, D24 and D27 | Probing the background form first (another live run, and `-p` wake behaviour is unknown); the default `EVAL_TIMEOUT` of 2,700 s (a hung arm overruns the cutoff); scoring a wait that never happened as a measured miss |
| D27 | Refines D4, D8 and D19: each track carries its conversation's request sequence. A candidate-changing effect (`tracked`, `unparsed`, `ttl_1h`, `thinking_budget`) applies only when its track is not older than the last applied one, and a `tool_use` completion marks the conversation pending only when it has sent nothing since; tested with overlapping requests | Standards review: comparing touch against the current candidate alone lets a delayed older `tracked` response recreate a candidate a newer `ttl_1h` response cleared, and an older `tool_use` completion restore pending after a newer request finished, against D4's latest candidate and D8's "nothing sent since" | Reviewer's call accepted as-is; comparing send times against a retained last-clear time (two clocks for one ordering, where `observe` already numbers requests under the lock) |
| D28 | Refines D6 and D10: a ping response that declares a length and ends short of it is `upstream_error` with the relay's `body ended after <n> of <declared> bytes`, is not parsed for usage, and ends the conversation `ping_failed` | Standards review: `read1` returns empty at a premature EOF without raising; the relay already checks the declared length (`cache_proxy._relay`) | Reviewer's call accepted as-is |
| D29 | Refines D15 and #429 D19: an AC3 arm's transcripts are the sessions whose root transcript's `cwd` is in the eval's sandbox repository, each with every transcript of its session id in any project directory | Standards review: a session that enters a worktree writes its subagents under the worktree's project directory (`agent_costs.find_sessions`), and the eval creates a worktree, so copying only sibling directories undercounts either arm | Reviewer's call accepted as-is; copying whole project directories (pulls in unrelated sessions run meanwhile) |
| D30 | AC2's child C waits with one foreground `python3 -c 'import time; time.sleep(480)'` in place of `sleep 480`, the same in both arms; the two off-arm attempts made with `sleep 480` are recorded void (`short_wait`) and the amended command gets one trial per arm with D26's single void rerun | The pinned Claude Code 2.1.302 Bash tool refuses a standalone `sleep 480`, so C never waited (gaps 12.6 s and 22.3 s); D14 needs one foreground 480 s wait in C, not the literal shell `sleep`, and the replacement keeps that wait and leaves `--keepalive` as the only difference between arms | Recording AC2 void with no evidence; a polling or backgrounded wait in C (D14 rejects shaping the evidence around the activity rule, and a background call returns at once) |
| D31 | Refines D6 and D28: one ping exchange is bounded by `PING_TIMEOUT` overall, measured on the keepalive's clock from the ping's send time; past it the read stops, the `ping` line reads `upstream_error` with `ping exceeded 30.0 s`, and the conversation ends `ping_failed` | Final correctness review CR-001: the 30 s socket timeout bounds each read, not the exchange, so a response that keeps trickling bytes held a ping in flight indefinitely, and `tick` skips a record with an in-flight ping before its ceiling check, keeping its credentials past the 60-minute bound | A separate, longer exchange bound (a second timeout constant with no measured need); leaving the exchange unbounded and relying on the ceiling (which never runs while the ping is in flight) |
