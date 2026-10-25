# Cache proxy: close the routed TTFT gap or stop routing by default — issue 438

Design for https://github.com/fagenorn/nix-config/issues/438. Base: `3f4c5072`
(`origin/main`). Approval source: autonomous (--auto), decision ledger. A bare
"Dn" cites this spec's ledger; "422 Dn" cites the #422 design spec
(`2026-10-24-issue-422-cache-proxy-design.md`).

## Triage

Input signals: `contract_change` hit (the wrapper's default routing is a user-facing launch contract AC3 may flip), `concurrency_or_persistence` no (per-launch env selection, stateless forwarding), `open_design_questions` hit (the shipped combination or opt-in is decided by measurement), `criteria_shape` hit (AC2 is a live TTFT measurement no deterministic check verifies). Predicted paths: `home/common/claude-code/accounts/bin/claude-account`, `home/common/claude-code/default.nix`, `python/agent_tools/cache_proxy.py`, `tests/test_cache_proxy.py`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md`. Verdict `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`; ran: full (shadow).

## Problem

Since #422, every `claude` launch goes through the loopback cache proxy
whenever its health check answers. Today the proxy only passes requests
through, and #429 owns the caching work, so routing buys nothing yet. It does
cost something. Both of #422's time-to-first-token measurements put the routed
median above direct: +511.5 ms, then +221.5 ms, against a +100 ms bound. A
routed session also has no Remote Control. The proxy hop itself costs about
0.3 ms (422 D27). The gap comes from what Claude Code sends when
`ANTHROPIC_BASE_URL` is not `api.anthropic.com`. The user wants no latency
added for no reason: either routed launches get as fast as direct ones, or
`claude` stops routing by default.

## Solution

The work has three stages. All of them run in the execute phase on mbp,
against the live API, from the built but never activated outputs. Nothing is
switched.

1. **Capture (AC1).** Record exactly how a proxied request differs from a
   direct one on the pinned Claude Code 2.1.302. One wire-level instrument
   captures both arms (D1).
2. **Screen.** Measure each of the issue's levers, and the two cheaper
   combinations they imply, with #422's time-to-first-token harness. The
   harness changes only where a fair comparison needs it (D2, D3), and the
   decision rule is fixed before any number exists (D4).
3. **Ship one of two branches.**
   - **Pass branch.** The cheapest lever that passed its screen is built into
     the wrapper, the proxy or both (D6, D7). One confirmation run at the final
     head then decides AC2.
   - **Opt-in branch (AC3).** This branch ships when no lever passed, when the
     confirmation failed, or when no valid confirmation could run. `claude`
     then routes only when `CLAUDE_CACHE_PROXY=1` is set (D8).

Either way, an evidence report records the diff, every run, the written
evaluation of TLS interception and the verdict (D9).

The Phase-0 carryover questions are settled as follows: the direct-arm
capture is D1, the opt-in switch is D8, the noise-honest rule is D4, the
service's fate under opt-in is D8, and the `HTTPS_PROXY` fallback is D5.

## Decisions

### What the pinned binary already says

These facts come from the strings of the pinned 2.1.302 binary. They make the
experiments precise, but they are not measurements. AC1 confirms them on the
wire.

- **First-party test.** Claude Code treats its endpoint as first-party when
  `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL` is set, or else when the base URL
  host is exactly `api.anthropic.com`. Several request features key off this
  test:
  - the dispatch header `anthropic-dispatch-id`: `v2d` for main-thread queries
    under a server flag, none for auxiliary queries, and `v2p` as the client's
    own fallback after a 5xx;
  - fine-grained tool streaming, under the `tengu_fgts` flag;
  - the other first-party request features.

  Remote Control checks the host directly, and the binary states that the
  variable does not apply to it.
- **Gzip gate.** Request-body gzip has its own gate:
  - the request URL host must be `api.anthropic.com`;
  - the body must be at least 4,096 characters;
  - there must be no HTTPS proxy, mTLS, extra CA (`NODE_EXTRA_CA_CERTS`) or
    unix socket.

  No variable restores gzip behind a loopback base URL. If the API answers a
  gzipped body with a 400 naming it unparseable JSON, Claude Code resends the
  identity body once and stops gzipping for the rest of the process.
- **Consequence.** Only the proxy can bring gzip back. The variable restores
  the client-side request shape. Neither restores Remote Control.

### AC1 capture

The instrument is `mitmdump`, from mitmproxy in a `devenv` ad hoc shell. Its
config directory and CA live in launch scratch, and it listens on port 27392.
It captures two sessions per arm. Each session runs the timed command line
(haiku, stream-json with partial messages, the same `ENABLE_TOOL_SEARCH` as
the timed runs) from the same scratch cwd, through the experiment wrapper
(below).

- **Direct arm.** The run sets `HTTPS_PROXY=http://127.0.0.1:27392`,
  `NODE_EXTRA_CA_CERTS` to the scratch CA, and a caller-set
  `ANTHROPIC_BASE_URL=https://api.anthropic.com`, which the wrapper leaves
  alone. The request keeps its first-party shape. The gzip gate turns
  compression off, so the diff marks the body-encoding row as derived from
  the binary, not observed.
- **Proxied arm.** The stock built proxy runs on 27391 with
  `--upstream http://127.0.0.1:27392`. mitmdump runs in reverse mode to
  `https://api.anthropic.com`, so it sees exactly what the proxy forwards.

**What gets committed.** A reduction runs per `/v1/messages*` request:

- **Headers.** Each arm's header names in order, with values only for #422's
  allowlist (422 D2) plus `anthropic-dispatch-id`, `content-encoding` and
  `accept-encoding`, and the `anthropic-beta` token-set difference.
- **Body.**
  - top-level keys, with values only for scalar non-content fields;
  - system block count, lengths and `cache_control`;
  - tool count, tool names and per-tool keys;
  - message count with block types and lengths;
  - input-side usage totals.
- **Differing text.** System and tool text lines that differ appear verbatim,
  except lines that contain the home directory path or a credential shape.
  Those are recorded only as a count and a byte length.

Raw flows stay in scratch and are deleted after reduction. A credential-shape
scan runs before every commit (422 D2).

**Missing first-party header.** A header present in every direct capture,
absent from every proxied one, and constant in value is a *missing first-party
header*. This set is E2's input.

**Fallback instrument.** If mitmdump cannot complete a direct session (TLS
refusal or auth failure), headers come from the SDK's own debug log
(`ANTHROPIC_LOG=debug`, whose `sending request` record masks `authorization`)
in both arms. Bodies then come only from the proxied reverse capture. The
report records which instrument ran and what it could not see.

**After the screens.** One more capture session runs the winner's proxied arm
and diffs it against the direct captures. The evidence then shows what the
lever changed on the wire.

### Experiment rig

- **Ports.** Every experiment cache-proxy, stock or prototype, uses port
  27391, and mitmdump uses 27392. The service's port 27183, 8160 and 4322 are
  never bound or probed.
- **Wrapper.** The experiment wrapper is a scratch copy of the built accounts
  mod whose one `CACHE_PROXY_URL=` line points at 27391; the copy asserts
  exactly one match. A `claude` script beside it execs the copy's
  `claude-account run`. Both arms launch through this wrapper, so the
  wrapper's health probe and exports stay in the measured path. The direct
  arm passes a caller-set first-party URL, exactly as in 422 D14.
- **Stock proxy.** The built `cache-proxy` launcher runs with the built
  launchd agent's command and environment, on `--port 27391`.
- **Prototype proxies.** These are used only to screen proxy-side levers. Each
  is a scratch copy of the worktree's `python/` package with one lever patched
  in, and no safety paths. It runs under the built launcher's interpreter,
  with the agent's environment and `PYTHONPATH` pointing at the copy.
  Prototypes are never committed. Only the winner is built into the product.
- **Levers.** A lever goes on the proxied arm only. The direct arm is the
  user's direct baseline and stays identical in every run.
- **Harness.** The harness is #422's `ttft.py` (task 5), kept in scratch, with
  the changes in D3. Everything else follows 422 D18 and D25:
  - one account;
  - `--model haiku`;
  - the `content_block_delta` clock;
  - the proxy-line validity check;
  - one process group per run, killed at 300 s;
  - per-request usage;
  - ten alternating pairs.
- **Process custody.** Every live command runs in the foreground under
  `launch-scope exec`. Every process a step starts is stopped before that step
  reports.

### Candidates

| ID | Lever on the proxied arm | Ships as | Undocumented reliance |
|----|--------------------------|----------|-----------------------|
| R0 | none (as shipped) | never: reference only | — |
| E3 | `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1` | wrapper export | none |
| G  | the proxy gzips the upstream body | proxy | none |
| E1 | `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` | wrapper export | the variable |
| C  | E1 + G | wrapper export + proxy | the variable |
| E2 | the proxy adds the missing first-party headers + G | proxy | the header semantics |

E3, E1 and E2 are the issue's three listed experiments. G and C are the
cheaper and the more complete combinations those experiments imply. If AC1
finds no missing first-party header, E2 is identical to G. In that case E2
drops out and G runs unconditionally in its place.

TLS interception through `HTTPS_PROXY`, the issue's fourth item, is evaluated
in writing only (D5).

### Decision rule

- **Validity.** A run is valid by 422 D18 and D25, plus the validity of its
  warm-up pair. An invalid run is rerun once. A second invalid run counts as
  not passing.
- **Pass.** A run passes when it is valid and Δ ≤ 100 ms, where Δ = median
  proxied TTFT − median direct TTFT over the ten counted pairs. That is AC2's
  literal bound. The diagnostics are recorded and never decide.
- **Cost rank.** Candidates are ranked by three keys, compared in order:
  1. the number of undocumented reliances shipped;
  2. client-decided request content before proxy-synthesized headers;
  3. wrapper-only before proxy changes.

  The resulting order is E3, G, E1, C, E2.
- **Screens.**
  - R0, E3, E1 and E2 always run.
  - G and C run only if no candidate ranked before them has passed.
  - No screen is ever repeated to get a different result.
- **Winner.** The winner is the first passing candidate in rank order. R0 can
  never win: it would ship the gap, and two failures are already on record.
  With no winner, the opt-in branch ships.
- **Confirmation.** The winner is implemented, built and confirmed by one run
  at the final head. The run uses the built proxy on 27391 and the
  experiment wrapper copied from the built mod. It sets no harness levers:
  the built wrapper and proxy supply them.
  - If it passes, AC2 is met and the pass branch ships.
  - If it fails, or is invalid twice, or the attempt deadline cutoff leaves no
    room for it (422 D20, D24), the winner's product commits are reverted and
    the opt-in branch ships.
- **Smoke run.** After a passing confirmation, one tool-use smoke run goes
  through the winner. A `claude -p` call must use the Read tool on a scratch
  file, print the file's first line and exit 0. If the smoke run fails, the
  winner breaks routed work: it is reverted and the opt-in branch ships.
- **Measured surface.** The confirmation stays AC2's measurement only while
  the measured surface is unchanged. That surface is the accounts mod, the
  claude-code Nix module, the `cache-proxy` module and the `claude-code` pin in
  `flake.lock`. Any later change to it, such as a review fix or an
  integration-branch merge that moves the pin, needs one new confirmation, and
  that run binds whatever it shows. Evidence and doc commits do not (422 D26).
- **Resolution.** The evidence report states the limits of this rule:
  - Run 2's own data gave Δ = +221.5 ms but a median within-pair difference
    of +80 ms. The per-arm interquartile ranges spanned about 0.45–1.0 s.
  - One n = 10 run cannot separate a lever's effect from noise at 100 ms.
  - With the run count capped and one confirmation, a lever that does nothing
    must pass twice by chance to ship. A lever that works can still fail its
    confirmation.
  - AC2's bound is the issue author's, and it stays the verdict.

### TLS interception (written evaluation)

`HTTPS_PROXY` with a locally trusted interception CA keeps `api.anthropic.com`
as the base URL. The request therefore keeps its first-party shape and Remote
Control stays available, but the gzip gate turns compression off. Its request
matches E1's, except where Claude Code checks the host itself, as Remote
Control does. The AC1 direct capture is exactly such a run. It is never
shipped: it would have a local CA intercept the user's OAuth traffic
on every launch. The evidence report records this evaluation, with the capture
as its observation (D5).

### Pass branch: what ships for each winner

- **Wrapper levers (E3, E1, C).** `route_cache_proxy` exports the lever only
  on a launch it routes.
  - **E3.** The variable is exported unless the caller set it, like
    `ENABLE_TOOL_SEARCH`. This reverses 422 D11's "fine-grained tool streaming
    stays off".
  - **E1's variable** belongs to the wrapper:
    - It is exported as `1` on every routed launch.
    - It is unset on every launch the wrapper decides not to route: after a
      failed probe, and with a caller-set URL other than the proxy's. No
      supported caller sets this variable, and an inherited copy would mark a
      caller's own endpoint as first-party.
    - A copy with no proxy URL still changes nothing.
    - An AC5 comment beside the export names anthropics/claude-code#98464 and
      "verified on Claude Code 2.1.302".
  - **`claude-local`** is unchanged. README § Cache proxy documents that it
    inherits a shipped lever when started inside a routed session, next to the
    existing `ENABLE_TOOL_SEARCH` note (422 D11, D13).
- **Proxy gzip (G, C, E2).**
  - **Scope.** The proxy gzips a `POST` whose path starts with `/v1/messages`,
    that has no client `Content-Encoding` and whose body is at least 4,096
    bytes. It sends `gzip.compress(body, compresslevel=6)` with
    `Content-Encoding: gzip` and the compressed `Content-Length`. Every other
    request is forwarded as today.
  - **Order.** Gzip is the last step before upstream, so #429's future body
    reshaping happens before it.
  - **Rejection.** A gzipped request may get a 400 whose error message is one
    of Claude Code 2.1.302's body-parse rejections: "The request body is not
    valid JSON", "Failed to parse request: could not parse request body as
    JSON", or a message matching `^bad json: `. The proxy then:
    1. reads that small answer without relaying it;
    2. resends the identity body once;
    3. relays the second answer;
    4. turns gzip off for the rest of its process, logging one
       `gzip_disabled` line with the status and error body.

    This copies the client's own policy, and it is the single exception to
    422 D6's no-retries rule.
  - **Log.** Request log lines gain `request_bytes` and
    `upstream_request_bytes`.
  - **Docs.** The `cache-proxy` section of the package README now describes
    the forwarding contract with this one change, instead of saying nothing
    is added.
- **Header restore (E2 only).** A fixed tuple in the proxy holds the missing
  first-party headers from AC1. The proxy adds each one to a `/v1/messages*`
  request that lacks it, and never edits a header the client sent. A comment
  names #98464 and 2.1.302, applying AC5's rule to an undocumented header. The
  report records the known cost: the proxy cannot tell query sources apart, so
  it sends `v2d` where the client would send nothing, and the client's `v2p`
  fallback is lost.
- **Routing default.** Routing stays on by default. README § Cache proxy
  names the shipped lever and links the evidence.

### Opt-in branch (AC3)

- **The switch.** `CLAUDE_CACHE_PROXY` is a closed set of values:
  - **`1`.** Today's routing: probe, export, and re-decide an inherited proxy
    URL.
  - **Unset or empty.** No probe runs. An `ANTHROPIC_BASE_URL` equal to the
    proxy URL is unset, so a child that opts out under an opted-in parent goes
    direct. Any other caller-set URL is left alone.
  - **Anything else.** `claude-account` dies with
    `CLAUDE_CACHE_PROXY must be 1 or unset` before claude starts.
- **The service** stays declared on both hosts, so opting in needs no rebuild,
  and #429 builds on it.
- **Docs.** The port comment in the claude-code Nix module and README § Cache
  proxy are rewritten so they no longer say that `claude` routes while the
  proxy is healthy. The README names `CLAUDE_CACHE_PROXY=1 claude` as the way
  in.
- **Product diff.** The diff is the switch with its tests and docs. Any winner
  commits are reverted first.

### Evidence

The evidence report `cache-proxy-ttft-gap.md` sits beside #422's spike report.
It holds:

- the conditions: built store paths, pinned version, account, ports and
  instruments;
- the AC1 diff;
- a screen table with each candidate's Δ, medians, diagnostics and validity;
- the confirmation run's pair table, shaped like the #422 spike report's
  Fact 3;
- the written TLS-interception evaluation;
- the verdict.

The acceptance record reads two whole-line markers:
`Shipped lever: <E3|G|E1|C|E2|none>` and `Routing default: <on|opt-in>`. Raw
per-request usage moves to a sibling file whenever the report would outgrow
one review member (422 D26). #422's spike report is a point-in-time record and
is not edited (D9). When the shipped branch relies on no `_CLAUDE_CODE_*`
variable, AC5 is recorded as not applicable.

### Coordination with #429

#429 edits the same proxy module. Defining gzip as the final step before
upstream makes it compose with a body transform. Overlaps are resolved at
merge time, and the #429 worktree is never touched.

## Test seams

- **Wrapper launch environment.** The tests run `claude-account run` from a
  substituted source copy, with the system `env` standing in for claude and
  the real `ProxyServer` answering health. This is #422's routing test seam
  (422 D15, D17).
  - **Pass branch.** The routed launch carries the lever. With E1 or C, a
    direct launch after a failed probe and a caller-set launch do not carry
    the variable, even when it is inherited.
  - **Opt-in branch.**
    - default with a healthy proxy: direct;
    - `1` with a healthy proxy: routed;
    - `1` with the proxy down: direct;
    - default with an inherited proxy URL: the URL is unset;
    - a caller-set URL: untouched under both;
    - a bad value: a nonzero exit, the message on stderr, and claude never
      runs.
- **Proxy forwarding.** This seam applies only if G, C or E2 ships. An
  in-process `ProxyServer` runs against a fake loopback upstream that records
  the bytes it receives (#422's proxy test seam).
  - The upstream receives gzip with the right headers, and it decompresses to
    the client's bytes.
  - Small bodies, non-messages paths and bodies the client already encoded
    arrive verbatim, so the existing verbatim-headers test still covers them.
  - A body-parse 400 produces one identity resend, a 200 to the client,
    identity on the next request and exactly one `gzip_disabled` line.
  - E2's headers are added once and never duplicated.
- **Live.** The scratch harness and the capture run against the built
  outputs (AC1, AC2). Nothing live is committed as a test.
- **Build.** `just build mbp` and CI `Nix Eval` cover the build.
  `claude-local` stays unchanged by construction: the diff has no change under
  its module.

## Out of scope

- #429's prefix reorder and any other request-body reshaping.
- Remote Control behind the proxy.
- `claude-local` changes, including an unset of the shipped lever (D6).
- Cutting the health probe's cost (about 25 ms). It stays inside the measured
  gap.
- Shipping TLS interception through `HTTPS_PROXY`.
- A build-time check that a future pinned binary still honours the
  first-party variable.
- Re-running or editing #422's spike and its report.
- `just switch` or activation, and anything bound to the service's port
  27183.
- Moving the `claude-code` pin.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | AC1 uses one wire-level instrument for both arms: mitmdump from a devenv ad hoc shell (CA in scratch, port 27392); the direct arm goes through `HTTPS_PROXY` plus `NODE_EXTRA_CA_CERTS` with a caller-set first-party URL, and the proxied arm through the stock proxy with mitmdump as its upstream in reverse mode; two sessions per arm on the timed command line; the committed diff holds header names, allowlisted values (422 D2 plus dispatch and encoding headers), body structure and scanned differing text lines, while raw flows stay in scratch and are deleted; body encoding is code-derived for direct (the gzip gate); the fallback is the SDK debug log for headers when mitmdump fails | Issue scope 1 ("logging-only TLS-intercepting setup or Claude Code's own debug logging"); the spike captured the proxied arm only; 422 D2 never persists credentials; user CLAUDE.md: missing tools via devenv ad hoc; the binary's SDK log records headers before the gzip middleware and passes bodies only through the console inspector | SDK debug log as the primary instrument (bodies truncated, transport not seen); capturing only the proxied arm again (AC1 needs both); a hosts-file interception keeping native gzip (needs root and a system CA) |
| D2 | Experiments use port 27391 for every cache-proxy and run both arms through a scratch copy of the built accounts mod with its one proxy-URL line substituted, so the wrapper's probe and exports are measured; proxy-side levers are screened as uncommitted scratch prototypes, and only the winner is built; levers go on the proxied arm only and the direct arm stays the fixed user baseline (422 D14, D18) | User constraint: ports other than 27183, 8160 and 4322, and no switch; the built wrapper hard-codes 27183; AC2 compares what a user gets each way | A caller-set proxy URL on the proxied arm (skips the probe and the wrapper's exports, so not what ships); implementing every lever in the product before screening (dead code for every loser); setting levers in both arms (E3 would change the baseline) |
| D3 | The harness is 422's `ttft.py` with five changes only: one discarded but validity-checked warm-up pair; repeatable `--proxied-env KEY=VALUE`; a scrub of every lever, proxy, CA, log and opt-in variable from the inherited environment; the matching proxy-log `ttfb_ms` and `upstream_conn` per proxied run; and per-arm quartiles plus the median within-pair difference as diagnostics | Each candidate changes the proxied request, so its first proxied run pays a cache write while the direct arm stays warm (run 2's pair 0 wrote cache in both arms); this session's environment would otherwise leak into both arms | No warm-up (systematically biased against every new candidate); more than 10 counted pairs (AC2 fixes 10 per arm); a new harness (422 D18 and D25 conditions already reviewed twice) |
| D4 | The decision rule is fixed before measurement: a pass is a valid run with Δ of medians ≤ 100 ms (AC2's literal bound), and diagnostics never decide; the rank by undocumented reliances, then client-decided content, then wrapper-only gives E3, G, E1, C, E2; R0, E3, E1 and E2 always screen, while G and C screen only if nothing ranked before them passed; screens are never repeated, and an invalid run is rerun once; the first passing candidate in rank is built and confirmed by one run at the final head; a failed, twice-invalid or deadline-skipped confirmation, or a failed tool-use smoke run, reverts the winner and ships opt-in; a change to the measured surface needs one new binding confirmation | Issue: "ship the cheapest combination", "each measured", AC2/AC3 and "shipping routing-by-default with the gap is not acceptable"; 422 D27 rejects re-measuring until a pass; AC5 shows the author weighs undocumented reliance; run 2: Δ +221.5 ms against a +80 ms within-pair median | A significance test (n = 10 has no power at 100 ms, and AC2's literal bound governs); a full factorial (more runs, more fluke passes); falling through to the next passer after a failed confirmation (multiple confirmations inflate false passes); R0 as a candidate (it ships the gap) |
| D5 | TLS interception through `HTTPS_PROXY` is evaluated in writing, with the AC1 direct capture as its observation, and never shipped | Phase-0 disposition (evaluate only); the binary's gzip gate excludes HTTPS proxies and custom CAs, so its request matches E1's except where Claude Code checks the host itself | Timing it (E1 measures that request shape without a CA on the user's OAuth traffic); shipping it (a locally trusted CA intercepting every launch) |
| D6 | Wrapper levers are exported only on routed launches; E3 is exported unless caller-set (reverses 422 D11's "fine-grained tool streaming stays off" if E3 ships); E1's variable belongs to the wrapper, so it is exported `1` when routed and unset when the wrapper decides not to route, with the AC5 comment naming anthropics/claude-code#98464 and 2.1.302; `claude-local` is not edited, and its inheritance inside a routed session is documented | AC5; 422 D10 (decisions are per launch, and value identity marks inheritance); 422 D11 and D13 (inheritance documented, a claude-local unset rejected as a second home); the variable is undocumented, so no caller sets it | Declaring levers in the settings `env` (would reach direct and `claude-local` sessions too); leaving an inherited variable alone on caller-set launches (it would mark a caller's own gateway first-party); a claude-local unset (out of scope, second home) |
| D7 | Proxy gzip covers `POST /v1/messages*` with no client encoding and a body of at least 4,096 bytes, at level 6, as the final upstream step; a body-parse 400 to a gzipped request gets one identity resend and a lifetime latch logged as `gzip_disabled`, the single exception to 422 D6's no-retries rule; log lines gain `request_bytes` and `upstream_request_bytes`; E2 adds only the AC1-derived constant headers, to requests that lack them, with the query-source and `v2p`-fallback costs recorded | The binary's own gate, threshold and rejection policy (a resend then a latch); the bar: the log stream is the debugger; #429 reshapes bodies later | Relaying the rejection (every routed request fails once per proxy lifetime, and the client never resends because it did not gzip); no rejection path (one API-side rollout would break every routed launch); level 9 (CPU for no wire gain at this size); rewriting `anthropic-beta` (the body may lack the matching fields) |
| D8 | The opt-in branch uses `CLAUDE_CACHE_PROXY` as a closed set: `1` keeps today's routing; unset or empty means no probe, with an inherited proxy URL unset and any other caller URL untouched; any other value dies before claude starts; the service stays declared; any winner commits are reverted, so the product diff is the switch | AC3 ("opt-in only"); the wrapper's `CLAUDE_*` variable family; the bar: fail loud at a closed set; #429 builds on the service; Phase-0 default for question 4 | A Nix option (opting in would need a rebuild, while an exported variable can still be persisted in shell config); removing the service (opt-in would need a rebuild); keeping a screened but unconfirmed lever in opt-in routing (an undocumented reliance without a passing measurement) |
| D9 | Evidence lives in a new report beside #422's spike report, with `Shipped lever:` and `Routing default:` as whole-line markers for the acceptance record, raw usage in a sibling when over one review member, and #422's report unedited | The bar: point-in-time records keep their text; 422 D25 (whole-line machine reads); 422 D26 (sibling for usage, a record move is not a surface change) | Appending to the #422 spike report (a closed issue's record); acceptance reading prose lines (D25's two-line value bug) |
