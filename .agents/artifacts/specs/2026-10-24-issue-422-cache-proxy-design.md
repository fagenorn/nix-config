# Cache proxy: live-API spike, then a pass-through service behind a health-checked wrapper — issue 422

Design for https://github.com/fagenorn/nix-config/issues/422. Base: `7601d318`
(`origin/main`). A bare "Dn" cites this spec's ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "new agent-tools command-table row and the claude wrapper gains ANTHROPIC_BASE_URL routing behaviour"}, "concurrency_or_persistence": {"value": "hit", "evidence": "threaded HTTP proxy streaming responses plus a launchd/systemd user service lifecycle"}, "open_design_questions": {"value": "hit", "evidence": "the live-API spike is a go/no-go gate; port, health endpoint and service wiring are undecided"}, "criteria_shape": {"value": "hit", "evidence": "six acceptance criteria, three of them live evidence no deterministic code check verifies"}}, "paths": ["python/agent_tools/cache_proxy.py", "lib/agent-tools.nix", "home/common/claude-code/accounts/bin/claude-account", "home/common/claude-code/default.nix", "home/common/claude-code/README.md", "python/README.md", "tests/test_cache_proxy.py", "justfile", "docs/spikes/cache-proxy-spike.md"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

Prompt-cache entries for subagents expire five minutes after their last use.
Only a subscription's main conversation gets an hour. So a subagent that waits,
or a sibling that starts a little later, pays full input price for a prefix
another request already built. The planned remedy is a local proxy on
the API path that can later refresh and reshape requests. Before anything is
built on that idea, it must be shown on the live API, with the user's normal
subscription login, that Claude Code can be pointed at a local proxy at all,
that a one-token replay refreshes a cache entry, and that reordering a
subagent's opening message lets siblings share its start-up attachments. If
that holds, the user needs the proxy installed as a service that every `claude`
launch uses, without a dead proxy ever stopping work.

## Solution

Two stages, gated.

1. **Spike.** A throwaway harness on mbp establishes facts 1, 2 and 4 of the
   issue against the live API and writes a committed report with the raw usage
   object of every request. Facts 1, 2 and 4 must all hold for the attempt to
   continue (D1).
2. **Pass-through.** A standard-library `agent_tools` module, run by a new
   `cache-proxy` command, forwards every request and streamed response
   unchanged. It runs as a user service on both host families. The `claude`
   wrapper probes the proxy's health endpoint before each launch and routes the
   launch through it only when it answers. Fact 3 (no added time to first
   token) and the A/B eval are measured on this shipped proxy (D14).

## Decisions

### Spike

The spike is the plan's first task and a hard gate (D1). Its harness is one
throwaway Python process in the launch's scratch directory (D2): a recording
pass-through to `https://api.anthropic.com`, a driver that runs `claude -p`
through the installed `claude` wrapper with `ANTHROPIC_BASE_URL` set to the
harness, and a replayer. The replayer authenticates with the bearer header the
harness saw on the captured request, held only in that process's memory.
Captured request bodies stay in scratch. Header values are kept only for
non-credential headers (`anthropic-version`, `anthropic-beta`, `content-type`,
`user-agent`, `x-app`, `x-stainless-*`); every other header is recorded by name
only. The report carries usage objects and request metadata, never bodies or
credential values.

- **Fact 1: base URL honoured.** The fact holds when a `claude -p` session
  under the wrapper and OAuth login exits 0 with its answer, and every
  `/v1/messages*` request it sends through the harness gets a 2xx response. Any
  other request is recorded with its status. The report also records the
  request shape seen through a custom base URL: the `anthropic-beta` tokens,
  the tool count, whether tool search is present, and the cache-control TTLs.
  It records these with and without `ENABLE_TOOL_SEARCH=true` (D11), and notes
  Remote Control's documented disablement behind a non-first-party base URL as
  a finding for the user.
- **Fact 2: replay refreshes the TTL.** This is tested on 5-minute entries. A
  subscription's main conversation defaults to 1-hour TTL, so the capture
  sessions set the documented `FORCE_PROMPT_CACHING_5M=1`, and the report
  records the `cache_control` TTLs and the `ephemeral_5m`/`ephemeral_1h` split.
  Two single-turn, tool-free sessions, A and B, run at t0. Each prompt carries
  its own distinct block of at least 1,000 tokens, so that its part of the
  prefix is measurable. Only A is replayed, at about t0+3.5 min, with
  `max_tokens=1` and nothing else changed. Both original bodies are re-sent
  between t0+6 and t0+8 min. The fact holds when two things are true. First,
  A's replay and re-send each read at least 99% of A's original cached prefix
  (its `cache_read` plus `cache_creation`) and create no more than 1% of it.
  Second, B's re-send must create its own part of the prefix again, which shows
  its entry expired (D3). If the API rejects `max_tokens=1` under the captured
  thinking configuration, the fact fails. The rejection body is recorded, along
  with the smallest `max_tokens` the API accepts, for the user's information.
- **Fact 4: siblings share attachments.** One session dispatches two subagents
  of the same type with different delegation prompts, and the harness captures
  each one's first request. The transform moves the shared start-up attachment
  blocks ahead of the delegation prompt and puts a `cache_control` breakpoint on
  the last attachment. It stays within the four-breakpoint cap and moves an
  existing breakpoint if the cap is reached. Two arms run sequentially with
  `max_tokens=1`: the untransformed pair as the baseline, then the transformed
  pair. The fact holds when the transformed second sibling's `cache_read` is at
  least the attachment token count. That count is measured with the
  count-tokens endpoint. If the endpoint refuses the OAuth bearer, the count is
  the usage difference between the arms instead.
  The baseline is recorded so that the gain can be attributed to the reorder.
  If the siblings' attachments differ, the fact fails and the report says how
  (D4).

A failed fact 1 ends the attempt. So does a failed fact 2 or 4, which is
reported by name. In each case the spike report is committed in the worktree,
no PR is opened, and the issue stays open for the user's decision (D1). Before
the report is committed, a scan for credential shapes (`sk-ant-`, `Bearer `,
`oat01`) must find nothing.

### The `cache-proxy` command

`cache-proxy --port N [--upstream URL]` serves until killed. It binds only
`127.0.0.1`, and no flag changes that. `--port` is required, because the port's
only home is Nix (D5). `--upstream` defaults to `https://api.anthropic.com`
and exists for tests. Port 0 binds an ephemeral port. On startup the command
writes one JSON line `{"event":"listening","host":…,"port":…,"upstream":…}` to
stderr. A bind failure exits non-zero with its error logged. `--help` prints
`usage: cache-proxy …` and exits 0, which the installed-layout test requires of
every command-table row. Without `--port`, the command exits 2 and serves
nothing.

The command reserves `GET /_proxy/health`, which answers `200`
`application/json` `{"service":"cache-proxy","status":"ok"}`. Any other method
on that path gets `405`. The path is never forwarded, and no other path is
reserved. The proxy holds no credential: it forwards whatever authentication
each client sends.

The module follows the agent-helpers thin-shell rule: argument parsing and
`main` delegate to importable functions that build and run the server, so
tests run it in-process. Nothing runs at import time.

### Forwarding contract (D6, D7)

- **Requests.** The method, path with query, and body bytes are forwarded
  verbatim. Every end-to-end header keeps its name, order and duplicates,
  including `authorization`, `x-api-key`, `anthropic-*` and `accept-encoding`.
  `Host` becomes the upstream host. Hop-by-hop headers (`connection`,
  `keep-alive`, `proxy-*`, `te`, `trailer`, `transfer-encoding`, `upgrade`, and
  any header that `connection` names) are dropped. The proxy adds no header of
  its own. A request body must carry `Content-Length`, and a chunked request
  body gets `411`.
- **Responses.** The status and end-to-end headers are forwarded the same way.
  The proxy adds nothing of its own, such as `Server` or `Date`. A sized body
  is forwarded with its length. An unsized body (SSE) is re-chunked to the
  client, one chunk per upstream read, and each chunk is flushed as soon as it
  arrives. Compressed bodies are never decoded. A response that carries no body
  under HTTP rules (`HEAD`, 1xx, 204, 304) is forwarded without one.
- **Failures.** If the upstream connect or send fails before any response
  arrives, the client gets `502` with an Anthropic-shaped error body,
  `{"type":"error","error":{"type":"api_error","message":"cache-proxy: …"}}`.
  The proxy never retries, because Claude Code owns retries. If the upstream
  fails mid-body, the client connection is closed without the terminating
  chunk, so a truncated stream never presents as complete. If the client hangs
  up mid-stream, the upstream response is abandoned and its connection closed.
- **Upstream connections.** Each client connection has at most one keep-alive
  upstream connection. It is reused only when the previous response was read to
  the end and the socket is not readable while idle, which would mean the peer
  closed it. Otherwise the proxy opens a fresh connection. TLS uses the default
  verified context, and the read timeout is 600 s, which matches Claude Code's
  default request timeout.
- **Concurrency.** The server runs one daemon thread per client connection,
  with a listen backlog of 64, so a burst of subagent connections is not
  refused. A client connection that sits idle for 600 s is closed, along with
  its upstream connection. Log lines are written whole, under a lock.
- **Log (D8).** The proxy writes one JSON line per request to stderr. The line
  has `method`, `path`, `status`, `upstream_conn` (`new` or `reused`),
  `ttfb_ms`, `duration_ms`, `bytes` and `outcome` (`complete`, `client_closed`,
  `upstream_error` or `rejected`). It never contains header values or bodies,
  with one exception: when the upstream status is 400 or higher, it includes up
  to 4 KiB of the error body, which is still forwarded unchanged.

### Service (D9)

One Nix binding holds the port, `27183`, which is loopback-only and below both
operating systems' ephemeral ranges. Two things consume it: the service's
argument vector and the wrapper's build-time substitution. The service runs the
`cache-proxy` launcher's store path with `--port 27183`. It sets `SSL_CERT_FILE`
to the nixpkgs CA bundle, so upstream TLS verification never depends on the
login environment.

- **darwin (mbp, eleven-m5).** A home-manager launchd agent,
  `claude-cache-proxy`, with `RunAtLoad` and `KeepAlive`. stdout and stderr go
  to `~/Library/Logs/claude-cache-proxy.log`.
- **anis-desktop.** A home-manager systemd user service, `claude-cache-proxy`,
  with `Restart=always` and `WantedBy=default.target`. Its log is the journal.

Both are declared in the claude-code module beside the wrapper and gated by
platform. `cache-proxy` is a command-table row like every other `agent_tools`
command, so it is also on `~/.agents/bin`.

### Wrapper routing (D10, D11, D12)

The `claude` launcher (`claude-account run`) gains one routing step. It runs
before every launch: the early exec for a caller-chosen config directory, the
first launch, and each `/account` switch relaunch. The proxy URL is a script
variable that is empty in source and that the build rewrites to
`http://127.0.0.1:27183`, the same mechanism that rewrites the tool paths.

1. If the URL is empty, nothing is routed.
2. If `ANTHROPIC_BASE_URL` is set, non-empty and different from the proxy URL,
   it is the caller's own endpoint and stays untouched. This covers a session
   started under `claude-local`, whose shim URL is such a value.
3. Otherwise, either because it is unset or because an outer launch set it to
   the proxy URL, the step probes `<url>/_proxy/health`. It runs the build's
   `curl` with `-q --noproxy '*' -fsS --max-time 0.5`. If the answer is 2xx and
   its body, checked with the build's `jq`, names `"service":"cache-proxy"`,
   the step exports the proxy URL. Anything else unsets `ANTHROPIC_BASE_URL`,
   so the launch goes direct. That includes a foreign listener on the port. A
   refused connection fails in milliseconds, and a hung proxy costs at most
   0.5 s. The step prints nothing on either outcome, because stdout and stderr
   belong to `claude`.
4. When it routes, the step also exports `ENABLE_TOOL_SEARCH=true` unless the
   caller set it. Claude Code documents that before 2.1.304 it turns tool
   search off behind a non-first-party base URL, and the pin is 2.1.302. This
   switch ships only if fact 1's capture shows that it restores deferred tool
   loading. Fine-grained tool streaming, also off behind a gateway, is left off
   (D11).

The health check runs at launch only. A session that launched while the proxy
was healthy stays on it. If the proxy dies mid-session, the service manager
restarts it and Claude Code's own retries cover the gap. A dead proxy never
blocks a new launch (D12). Remote Control stays unavailable on a routed session.
`ANTHROPIC_BASE_URL=https://api.anthropic.com claude` is the per-launch way to
go direct, by rule 2.

### claude-local

`claude-local` is not changed. It never receives the proxy URL, for two
reasons. It execs the pinned binary directly, not the wrapper. It also exports
its own `ANTHROPIC_BASE_URL` unconditionally before that exec, which replaces
any proxy URL inherited from a routed parent session (D13). A `claude-local`
started from inside a routed session does inherit `ENABLE_TOOL_SEARCH=true`.
The claude-code README documents this, together with the fact that the next
pin past 2.1.304 makes tool search the default behind any gateway regardless.

### Live evidence (D14)

All live evidence runs on mbp against the built configuration, not an
activated one. No agent runs `just switch`. The built `cache-proxy` launcher,
started in the foreground with the service's arguments and environment, stands
in for the running service, and stopping it stands in for a stopped service. The built
`claude` wrapper is put first on `PATH`.

- **Eval.** `just evals from-issue 1` must pass in both arms. The report
  records the proxy log's line count for each run: more than zero when the
  proxy is healthy, zero when it is stopped. It also records both arms' token
  totals, so that a request-shape change shows up.
- **Time to first token.** Ten pairs of identical `claude -p` requests run in
  alternating order: one through the proxy, one direct with
  `ANTHROPIC_BASE_URL=https://api.anthropic.com`. Time to first token is
  measured client-side, from launch to the first streamed content event. The
  proxied median must be within +100 ms of the direct median. This measurement
  is fact 3 in the spike report.
- **Builds.** `just build mbp`, and an eval of
  `nixosConfigurations.anis-desktop`, the same check CI's Nix Eval runs.

The service declarations themselves are proved by the build and evaluation
only. The user's demo after activation is outside the attempt.

### Docs

`python/README.md` gets a `cache-proxy` section covering the command contract,
the health path and the log fields. The claude-code README gets a cache-proxy
section covering the service, the routing rules, logs, Remote Control, the
per-launch way to go direct, a nested `claude-local`'s inherited switch, and the
unrotated darwin log. CLAUDE.md and
AGENTS.md do not change, so the instruction budget is untouched. The spike
report lives at `docs/spikes/cache-proxy-spike.md`, a point-in-time record that
the PR links.

## Test seams

All tests are new unittest files added to `just agent-workflow-tests`.

- **Proxy, in-process (D15).** The test starts the server on port 0 against a
  fake upstream, a threaded stdlib server on loopback that records the raw
  request and replays a scripted response. The tests cover:
  - an SSE response whose de-chunked bytes are identical to upstream's, with
    each event delivered before the next is released (the fake upstream holds
    between events);
  - request headers, including `authorization` and duplicates, arriving at
    upstream in order with only `Host` changed and nothing added;
  - the health path answering without reaching upstream;
  - a `502` with the error envelope when upstream is unreachable;
  - an upstream reset mid-stream, which leaves the client's body unterminated;
  - a second request on one client connection that reuses the upstream
    connection.
- **Proxy command.** `python -m agent_tools.cache_proxy --port 0 --upstream …`
  runs as a subprocess. The test reads the port from the `listening` line,
  makes one round trip, and terminates it.
- **Wrapper.** The test runs the source `claude-account run` from a temporary
  copy of the accounts mod. The copy's proxy URL is substituted as the build
  substitutes it. The environment is scrubbed of the session's own
  `CLAUDE_CONFIG_DIR`, `CLAUDE_ACCOUNT`, `ANTHROPIC_BASE_URL` and
  `ENABLE_TOOL_SEARCH`. `HOME` and `CLAUDE_ACCOUNTS_DIR` are temporary, and
  `CLAUDE_BIN` is a fake `claude` that writes its environment to a file. Six
  cases run:
  - health up: routed, with `ENABLE_TOOL_SEARCH`;
  - health down (a closed port, or a foreign 200 without the marker): unset;
  - a caller-set non-proxy URL with health up: untouched;
  - an inherited proxy URL with health down: unset;
  - a caller-chosen `CLAUDE_CONFIG_DIR` with health up, which takes the early
    exec: routed;
  - an unsubstituted source copy: never routed.

  The bash-driving precedent is `tests/test_branch_protection.py`.

## Out of scope

- Any request mutation, replay, keep-warm or caching logic. That is the
  follow-up slice. The spike harness is not committed.
- Parsing usage or bodies inside the proxy.
- Log rotation on darwin: the launchd-held log is append-only and documented
  as such.
- Mid-session failover.
- Non-loopback binding, HTTP/2, and chunked request bodies.
- Environments that set `HTTP_PROXY`/`HTTPS_PROXY`.
- Changes to `claude-local`, to `claude-account login` or `status`, to
  CLAUDE.md, and to host activation (`just switch` stays the user's).
- Restoring fine-grained tool streaming or Remote Control on routed sessions.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Spike is plan task 1 and a hard gate: facts 1, 2, 4 must hold; any failure commits the report in the worktree, opens no PR and ends the attempt naming the failed fact; fact 3 is not a gate and is recorded from the shipped proxy's TTFT run | Issue's go/no-go text and "go requires facts 1, 2 and 4" | Building the pass-through first and spiking through it: wasted work if fact 1 fails, and the issue orders spike first |
| D2 | Spike harness is one throwaway process in launch scratch; the replay bearer is the captured request's header held in memory only; bodies stay in scratch; only allowlisted header values are kept; report holds usage and metadata; credential-shape scan before commit | Issue's "never persist auth headers" constraint; agent-helpers rule 1 bars committed top-level scripts | Reading the token from the keychain (second credential read, GUI-prompt risk); committing the harness (untested non-package Python) |
| D3 | Fact 2 runs on 5-minute entries forced with `FORCE_PROMPT_CACHING_5M=1`, single-turn tool-free sessions with distinct ≥ 1,000-token blocks, a paired unreplayed control re-sent at t0+6–8 min, a 99%/1% tolerance, and a strict fail when `max_tokens=1` is rejected (smallest accepted value recorded as information) | Claude Code docs: subscription main conversation defaults to 1h TTL; thinking `enabled` needs `budget_tokens` ≥ 1024 < `max_tokens`; cache hits reset the TTL | Testing on default captures (1h TTL makes the refresh unobservable); redefining the fact around what the API accepts |
| D4 | Fact 4 transform reorders attachments ahead of the delegation prompt with one breakpoint after them, within the 4-breakpoint cap; an untransformed sequential baseline is recorded; the gate is the issue's threshold | Issue fact 4; API limit of four breakpoints | Judging the transformed arm alone (gain not attributable to the reorder) |
| D5 | `cache-proxy --port N [--upstream URL]`, loopback bind fixed, port required (its one home is Nix: 27183; `--help` exits 0 for the installed-layout test), reserved `GET /_proxy/health` → 200 `{"service":"cache-proxy","status":"ok"}`, never forwarded | DRY one home per constant; Anthropic API paths live under `/v1` and `/api`; `tests/test_agent_tools_launchers.py` runs every row with `--help` | A Python port default (second home); a configurable bind host (exposes an auth-forwarding proxy); a marker-less health body (a foreign listener's 200 would route sessions into it) |
| D6 | Verbatim forwarding in both directions (headers by name, order and duplicates, only `Host` rewritten, hop-by-hop dropped, nothing added); unsized bodies re-chunked per read; no proxy retries; pre-response failure → 502 Anthropic error envelope; mid-body upstream failure → close without terminating chunk; chunked request bodies → 411 | Issue: "forwards every request and streamed response unchanged"; the bar's truthful terminal states; `anthropic-shim.py` streaming precedent | Retrying a POST on a fresh connection (can double-send a billed request); terminating a truncated stream cleanly (presents as complete) |
| D7 | One keep-alive upstream connection per client connection, reused only if fully read and idle-unreadable | +100 ms TTFT criterion; the shim's fresh connection per request costs a TLS handshake each time | Fresh connection per request; a shared cross-thread pool (locking, YAGNI) |
| D8 | One JSON log line per request on stderr with named fields, no header values or bodies except ≤ 4 KiB of an upstream ≥ 400 body; darwin log unrotated and documented | The bar: the log stream is the debugger and failure paths log the provider's body; the issue demo needs request lines | newsyslog rotation (renaming a launchd-held file keeps the process writing to the old file) |
| D9 | launchd agent (RunAtLoad, KeepAlive) on darwin, systemd user service (Restart=always) on anis-desktop, both declared in the claude-code module beside the wrapper, running the launcher store path with `SSL_CERT_FILE` pinned to the nixpkgs CA bundle | Issue service shape; darktable `launchd.agents` precedent; launchd's minimal environment | Separate home/darwin and home/linux modules (split the port's one home); relying on the login environment for CA certificates |
| D10 | Routing runs in `claude-account run` before every launch, switch relaunches included; caller-set value ≠ proxy URL is untouched; unset or equal to the proxy URL is re-decided by a 0.5 s health probe (`curl -q --noproxy '*'`) that must return 2xx with the `cache-proxy` marker; empty source URL never routes; silent on both outcomes | Issue failure posture; the launcher already owns launch environment (plugin dirs, config dir); value identity distinguishes inherited from caller-set | Leaving any set value untouched (a nested launch would inherit a dead proxy); a marker variable (second state for one fact); a pre-wrapper script (switch relaunches would skip the probe) |
| D11 | A routed launch also exports `ENABLE_TOOL_SEARCH=true` unless caller-set, shipped only if fact 1 shows it restores deferred loading; fine-grained tool streaming stays off; Remote Control's loss and a nested `claude-local`'s inheritance of the switch are documented, and the former is surfaced in the spike report | Claude Code gateway docs: before 2.1.304 tool search is off behind a gateway (pinned 2.1.302); fine-grained tool streaming and Remote Control off for a non-first-party base URL | No parity switch (routed prompts carry every deferred tool inline); also exporting the streaming switch (no prompt or cost effect, and it would leak a beta into nested non-Anthropic sessions) |
| D12 | Health is checked at launch only; mid-session proxy death is covered by service restart plus Claude Code retries, and documented | Issue: "a dead proxy never blocks work"; a running process cannot change its base URL | In-session failover (not possible without client support) |
| D13 | `claude-local` unchanged; its never-receives guarantee is construction (direct pinned-binary exec plus unconditional export), and the wrapper test covers the caller-set case | Scope estimate; claude-local is Linux-only and its launcher is a Nix string | Refactoring claude-local into a source-testable script with a fake NInfer and the coproc shim in tests; a claude-local `unset` of the wrapper's switch (a second home for the switch list) |
| D14 | Live evidence on mbp uses the built, unactivated launcher and wrapper; no agent switches; eval arms record proxy log line counts and token totals; TTFT uses 10 alternating pairs with a client-side first-content clock, direct arm via caller-set first-party URL; that run is fact 3 | CLAUDE.md: switch only when asked; issue measurements | `just switch` during the attempt; back-to-back blocks per arm (drift lands on one arm) |
| D15 | Proxy behaviour is tested in-process against a fake loopback upstream plus one `python -m` subprocess round trip; the wrapper is tested from a substituted source copy with a fake `claude` | agent-helpers rule 5; the bar: assert observable bytes and environment, not calls | Mocking `http.client` (call assertions survive any implementation) |
| D16 | Proxy details the spec left open (refines D5, D6, D8): `GET /_proxy/health` and its `405` are answered without a log line; every log line carries `event` (`listening`, `bind_failed`, `request`) and `ts`; a request line whose outcome is `upstream_error` adds `error` (exception class and message); a chunked request body (`411`) or a non-numeric, negative or conflicting `Content-Length` (`400`; a request with neither header has no body) is answered with the Anthropic envelope typed `invalid_request_error`, logged `rejected`, and closes the client connection; a re-chunked response writes `Transfer-Encoding: chunked` after the forwarded headers; `Host` is rewritten in place, or prepended when the client sent none | The bar: the log stream is the debugger, structured fields; the eval arms' proxy-log counts must measure forwarded traffic only (D14) | Logging health probes (every routed launch adds a line, so a healthy arm counts > 0 with no forwarded request); a bare-status 411 (Claude Code parses Anthropic-shaped errors) |
| D17 | Verification venues and seams (refines D14, D15): AC4's anis-desktop half is CI's `Nix Eval`, because the toplevel `nix eval` needs an x86_64-linux builder for catppuccin's import-from-derivation and fails on mbp at base 7601d318; locally the plan evaluates the declared unit (`nixosConfigurations.anis-desktop.config.home-manager.users.anis.systemd.user.services.claude-cache-proxy`), both darwin agents, and builds mbp. The wrapper test runs `bash <copy>/bin/claude-account run` with `CLAUDE_BIN` set to the system `env`, which prints the environment claude would receive, and its health-up listener is the real `agent_tools.cache_proxy` server | Planning dry run of the CI command on mbp; `tests/test_branch_protection.py` (a host may refuse to exec a freshly written file); the bar: assert observable behaviour | Claiming a local toplevel eval (impossible on mbp without a Linux builder); a written fake-claude executable; a fake health server for the up case (would not prove the real health contract matches the wrapper's check) |
| D18 | Live-evidence conditions (refines D14): every live run uses one account, `CLAUDE_ACCOUNT` = the executing session's `claude-account active`, switched only on a usage-limit refusal to another signed-in account with headroom and recorded; spike sessions use the account's default model; TTFT pairs run `claude -p --model haiku --output-format stream-json --verbose --include-partial-messages` from a scratch directory with the same caller-set `ENABLE_TOOL_SEARCH` in both arms (only if the switch ships), first content = the first `stream_event` whose `event.type` is `content_block_delta`, and each proxied run must add ≥ 1 `/v1/messages` proxy-log line while each direct run adds 0; eval arms run healthy first, then stopped, each in one foreground command bounded by `EVAL_TIMEOUT` (2700 s) | TTFT variance must be small against a +100 ms threshold; identical requests apart from the base URL; the attempt deadline | The default model for TTFT (its first-token variance swamps 100 ms); the switch on the routed arm only (shrinks that arm's prompt and biases the comparison toward the proxy) |
| D19 | Spike measurement definitions (refines D3, D4, D11): fact 2's control holds when B's re-send creates ≥ 1,000 tokens (the block floor); fact 4's attachment count = count-tokens of a user message holding only the shared attachment blocks minus one holding `.` (same model, no system or tools), and if count-tokens refuses the bearer, transformed sibling 1's total input (`input + cache_read + cache_creation`) minus the same body's with the attachment blocks removed (one extra `max_tokens=1` request); fact 4's sends use the smallest `max_tokens` the API accepts under the captured thinking configuration when it refuses 1 (a cache read does not depend on it; fact 2 alone fails on that refusal, per D3); the tool-search switch ships only when the fact-1 captures show tool search absent without `ENABLE_TOOL_SEARCH=true` and present with it (present = a tool with `defer_loading: true` or a tool `type` starting `tool_search_tool`); the report carries the machine-readable lines `Fact 1:`, `Fact 2:`, `Fact 4:`, `Tool-search switch:` and `Verdict:` | Spec § Spike leaves these thresholds and the fallback count unstated; later tasks branch on the report | The arm difference as the fallback count (transformed sibling 2's read minus the baseline's makes the gate pass by construction) |
| D20 | Live evidence runs under a deadline cutoff: TTFT needs ≥ 15 min and each eval ≥ 50 min left before deadline − 60 min, with no rerun past it; a skipped run records `human-pending` with its exact command, making `acceptance_state` `human_pending` (issue held open with `needs-verification`), and Task 1's spike gate is never skipped | Phase-5 Codex review D1: the evals' up-to-180 min exceed the window before the 2026-10-25T01:42:25Z attempt deadline; ship needs review, CI and merge time | Running every live step regardless (would overrun the deadline and lose the delivery) or dropping AC5/AC6 (the issue's contract) |
