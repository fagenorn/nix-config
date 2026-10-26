# Cache proxy: the routed time-to-first-token gap — issue 438

§ Issue 450 below is the current basis for the routing default; the sections before it are #438's point-in-time record.

Point-in-time evidence for https://github.com/fagenorn/nix-config/issues/438, by the plan .agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.md; #422's record is docs/spikes/cache-proxy-spike.md.

## Conditions

- Date 2026-10-25, host `mbp`, commit `2823bf33`.

Claude Code version: 2.1.310

- Binary facts rechecked on 2.1.310, in the native executable `/nix/store/4vc9k1b3vwrj5prm2qkfskgx18dx9zlp-claude-code-2.1.310/bin/.claude-unwrapped` (the one the wrapper's `DEFAULT_CLAUDE_BIN` names through a 49 KB makeCWrapper script): `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`, `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING`, `The request body is not valid JSON`, `Failed to parse request: could not parse request body as JSON` and `bad json: ` are all present.
- Gzip threshold and gate, rechecked on 2.1.310 from the binary's request-compression code: the threshold is 4,096 characters of body (1,024 for the `ccr_worker` entrypoint), and compression is switched off with a recorded reason when `ANTHROPIC_UNIX_SOCKET` is set, when a proxy is configured and not bypassed for the URL, when an mTLS cert or key is set, and when `NODE_EXTRA_CA_CERTS` is set (outside narrow exemptions that were not traced).
- Rig store paths: wrapper module `/nix/store/v1qdl28023m8kkrn53gg8p1hvx1d4ysy-claude-accounts-mod`, agent plist `/nix/store/21j65c6xa7dhnrhwncvm2xlm9ngqfsi9-org.nix-community.home.claude-cache-proxy.plist`, launcher `/nix/store/ra815ss9bn1lcxi1v2sg2z3c8smpp2g1-agent-tools-cache-proxy`, interpreter `/nix/store/58dinqww5lhvj3cbr3lzbdlqhn3ypyvw-python3-3.13.12-env/bin/python3`.
- Account `p1` (by name only); ports 27391 (the stock cache-proxy) and 27392 (mitmdump); mitmproxy 12.2.3, started from a scratch devenv shell (`packages = [ pkgs.mitmproxy ]`, nixpkgs `github:cachix/devenv-nixpkgs/rolling`) because `devenv -O packages:pkgs "mitmproxy" shell` fails on devenv 2.0.2 with `undefined variable 'config'`.
- Instrument, direct arm: `mitmdump` as a forward proxy with `http2=false` and `--allow-hosts '^api\.anthropic\.com:443$'`, reached through `HTTPS_PROXY=http://127.0.0.1:27392` and `NODE_EXTRA_CA_CERTS` naming its CA, with `ANTHROPIC_BASE_URL=https://api.anthropic.com` set by the caller; every other host is tunnelled. Proxied arm: the stock built cache-proxy on 27391 with `--upstream http://127.0.0.1:27392`, and `mitmdump --mode reverse:https://api.anthropic.com` on 27392. Both arms record through one addon that keeps one reduced record per `/v1/messages` request: credential headers keep their name only, allowlisted headers keep their value, every other header keeps a 16-hex SHA-256 digest, and no flow file is written. Two sessions per arm.
- Timed command line (both arms, same cwd, scrubbed environment, `ENABLE_TOOL_SEARCH=true`): `claude -p --model haiku --output-format stream-json --verbose --include-partial-messages "Reply with exactly: ok"`, run through the wrapper copy with the proxy line pointed at 27391. Only the arm variables differ. The scrubbed variables are `ANTHROPIC_BASE_URL`, `ENABLE_TOOL_SEARCH`, `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING`, `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`, `CLAUDE_CODE_DISPATCH_V2D`, `CLAUDE_CODE_GZIP_REQUEST_BODIES`, `CLAUDE_CACHE_PROXY`, `HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY`, `http_proxy`, `ALL_PROXY`, `all_proxy`, `NO_PROXY`, `no_proxy`, `NODE_EXTRA_CA_CERTS`, `ANTHROPIC_LOG` and `ANTHROPIC_CUSTOM_HEADERS`.

## AC1 — direct versus proxied request

| Row | Direct | Proxied |
|---|---|---|
| beta-tokens | advanced-tool-use-2025-11-20, advisor-tool-2026-03-01, afk-mode-2026-01-31, cache-diagnosis-2026-04-07, claude-code-20250219, context-management-2025-06-27, dangerous-tool-use-2026-09-03, effort-2025-11-24, extended-cache-ttl-2025-04-11, inline-tools-2026-09-15, interleaved-thinking-2025-05-14, message-threads-2026-08-12, mid-conversation-system-clear-at-2026-08-21, mid-conversation-tool-changes-2026-07-01, oauth-2025-04-20, per-turn-control-2026-07-01, prompt-caching-scope-2026-01-05, thinking-binding-controls-2026-08-01, thinking-display-updates-2026-08-18, thinking-token-count-2026-05-13 | advanced-tool-use-2025-11-20, advisor-tool-2026-03-01, afk-mode-2026-01-31, claude-code-20250219, context-management-2025-06-27, dangerous-tool-use-2026-09-03, effort-2025-11-24, extended-cache-ttl-2025-04-11, inline-tools-2026-09-15, interleaved-thinking-2025-05-14, mid-conversation-tool-changes-2026-07-01, oauth-2025-04-20, per-turn-control-2026-07-01, thinking-display-updates-2026-08-18, thinking-token-count-2026-05-13 |
| body-bytes | raw 69521 (derived: the binary's gzip gate turns compression off under HTTPS_PROXY and NODE_EXTRA_CA_CERTS, so a plain direct launch sends this body gzipped (spec § What the pinned binary already says)), decoded 69521 | raw 67692, decoded 67692 |
| body-encoding | identity (derived: the binary's gzip gate turns compression off under HTTPS_PROXY and NODE_EXTRA_CA_CERTS, so a plain direct launch sends this body gzipped (spec § What the pinned binary already says)) | identity |
| body:diagnostics | {previous_message_id} | (absent) |
| body:keys | context_management, diagnostics, max_tokens, messages, metadata, model, output_config, safeguards, stream, system, thinking, thread, tools | context_management, max_tokens, messages, metadata, model, output_config, safeguards, stream, system, thinking, tools |
| body:thread | {type} | (absent) |
| header-order | accept, authorization, content-type, user-agent, x-claude-code-session-id, x-stainless-arch, x-stainless-lang, x-stainless-os, x-stainless-package-version, x-stainless-retry-count, x-stainless-runtime, x-stainless-runtime-version, x-stainless-timeout, anthropic-beta, anthropic-dangerous-direct-browser-access, anthropic-dispatch-id, anthropic-version, x-app, x-claude-code-prompt-id, x-claude-code-request-class, x-client-request-id, connection, accept-encoding, content-length | accept, authorization, content-type, user-agent, x-claude-code-session-id, x-stainless-arch, x-stainless-lang, x-stainless-os, x-stainless-package-version, x-stainless-retry-count, x-stainless-runtime, x-stainless-runtime-version, x-stainless-timeout, anthropic-beta, anthropic-dangerous-direct-browser-access, anthropic-version, x-app, accept-encoding, content-length |
| header:anthropic-beta | oauth-2025-04-20,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,prompt-caching-scope-2026-01-05,claude-code-20250219,per-turn-control-2026-07-01,mid-conversation-tool-changes-2026-07-01,inline-tools-2026-09-15,advisor-tool-2026-03-01,advanced-tool-use-2025-11-20,mid-conversation-system-clear-at-2026-08-21,effort-2025-11-24,dangerous-tool-use-2026-09-03,thinking-binding-controls-2026-08-01,thinking-display-updates-2026-08-18,afk-mode-2026-01-31,extended-cache-ttl-2025-04-11,cache-diagnosis-2026-04-07,message-threads-2026-08-12 | oauth-2025-04-20,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,claude-code-20250219,per-turn-control-2026-07-01,mid-conversation-tool-changes-2026-07-01,inline-tools-2026-09-15,advisor-tool-2026-03-01,advanced-tool-use-2025-11-20,effort-2025-11-24,dangerous-tool-use-2026-09-03,thinking-display-updates-2026-08-18,afk-mode-2026-01-31,extended-cache-ttl-2025-04-11 |
| header:anthropic-dispatch-id | v2d | (absent) |
| header:connection | constant | (absent) |
| header:content-length | constant | constant |
| header:x-claude-code-request-class | constant | (absent) |
| messages:1:blocks | text:21799, tool_addition:532, tool_addition:623, tool_addition:933 | text:21687, tool_addition:501, tool_addition:592, tool_addition:902 |
| system:0:len | 192 | 74 |
| system:1:cache_control | null | {"ttl": "1h", "type": "ephemeral"} |
| system:2:cache_control | {"scope": "global", "ttl": "1h", "type": "ephemeral"} | {"ttl": "1h", "type": "ephemeral"} |
| system:2:len | 2025 | 7101 |
| system:3:cache_control | {"ttl": "1h", "type": "ephemeral"} | (absent) |
| system:3:len | 6049 | (absent) |
| system:count | 4 | 3 |
| tools:Agent:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:Bash:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:Edit:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:ListAgents:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:Read:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:ReportFindings:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:ScheduleWakeup:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:Skill:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:ToolSearch:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:Workflow:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:Write:keys | description, eager_input_streaming, input_schema, name | description, input_schema, name |
| tools:advisor:keys | defer_loading, model, name, type | (absent) |
| tools:count | 13 | 12 |
| tools:names | Agent, Bash, Edit, ListAgents, Read, ReportFindings, ScheduleWakeup, Skill, ToolSearch, Workflow, DeferredToolPlaceholder, Write, advisor | Agent, Bash, Edit, ListAgents, Read, ReportFindings, ScheduleWakeup, Skill, ToolSearch, Workflow, DeferredToolPlaceholder, Write |

`body-encoding` is shown although both arms read identity; it is not one of the 33 diff rows.

Beta tokens only direct: cache-diagnosis-2026-04-07, message-threads-2026-08-12, mid-conversation-system-clear-at-2026-08-21, prompt-caching-scope-2026-01-05, thinking-binding-controls-2026-08-01
Beta tokens only proxied: none
Within-arm varying rows: header:x-claude-code-prompt-id, header:x-claude-code-session-id, header:x-client-request-id, usage:cache_creation, usage:cache_creation_input_tokens, usage:cache_read_input_tokens

Lines only in the direct arm's first session:
~~~~
x-anthropic-billing-header: cc_version=2.1.310.754; cc_entrypoint=sdk-cli; cch=<session-scoped>; cc_prompt_id=<session-scoped>; cc_turn_origin=sdk; cc_prompt_index=0; cc_turn_index=1;
 - If the user asks about "ultrareview" or how to run it, explain that /code-review ultra launches a multi-agent cloud review of the current branch (or /code-review ultra <PR#> for a GitHub PR); /ultrareview is a deprecated alias for the same command. It is user-triggered and billed; you cannot launch it yourself, so do not attempt to via Bash or otherwise. It needs a git repository (offer to "git init" if not in one); the no-arg form bundles the local branch and does not need a GitHub remote.
<harness token-budget line, session-scoped>
WebSearch takes a `mode`. Use "standard" by default: it is the normal search, quick and cheap. Use "extended" only when a "standard" result comes back thin, off-target or possibly outdated, or from the start for hard-to-find or niche facts, very recent events, prices and availability, and multi-step research: it is thorough and fresh but several times the cost. When you plan several searches, send them in the same turn.
~~~~

Lines only in the proxied arm's first session:
~~~~
x-anthropic-billing-header: cc_version=2.1.310.754; cc_entrypoint=sdk-cli;
~~~~

Missing first-party headers: anthropic-dispatch-id=v2d
Missing first-party headers without a recorded value: connection, x-claude-code-request-class

`connection` is a hop-by-hop header and is not a forwarding candidate for E2's `FIRST_PARTY_HEADERS`.

## TLS interception (written evaluation)

`HTTPS_PROXY` with a locally trusted interception CA keeps `api.anthropic.com` as the base URL, so the request keeps its first-party shape and Remote Control stays available, but the client's gzip gate turns compression off. The AC1 direct sessions above are exactly such runs: they differ from a plain direct launch in the body-encoding row, which shows identity here where a plain direct launch sends this body gzipped, and in the raw half of the body-bytes row, which is derived from the same interception (a plain direct launch's raw size is smaller than the decoded 69521 shown), and this evidence does not isolate any other row that the interception changes. It is not shipped, because a locally trusted CA would intercept the user's OAuth traffic on every launch (D5).

## Screens

- Date 2026-10-25, commit `84b37547`, rig as in § Conditions, account `p1`, attempt `deadline_at` 2026-10-26T02:14:43Z. The deadline cutoff computation read 164 minutes before R0 and 158 before E2, against the 70-minute minimum, so no candidate was skipped for the deadline. Wire check: one `claude -p` session through mitmdump behind the candidate's proxy, reduced by `reduce.py check` against the AC1 rows. Timed run: `python3 -I ttft.py --rig <rig> --proxy-log <candidate>.log --out <candidate>.json` with one `--proxied-env KEY=VALUE` per lever variable (E3 `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`, E1 `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1`, none for R0 and E2), against the stock proxy for R0, E3 and E1 and against the scratch prototype for E2. Timing runs never went through mitmdump.

| Candidate | Lever | Wire check | Valid | Median proxied ms | Median direct ms | Δ ms | Passes | Quartiles proxied | Quartiles direct | Median within-pair ms |
|---|---|---|---|---|---|---|---|---|---|---|
| R0 | none (stock proxy) | — | true | 2820.5 | 2526.5 | 294.0 | false | [2562.25, 2820.5, 2902.75] | [2333.25, 2526.5, 2800.75] | 160.0 |
| E3 | `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1` | holds | true | 2564.5 | 2522.5 | 42.0 | true | [2102.75, 2564.5, 3179.5] | [2281.75, 2522.5, 3278.5] | -57.5 |
| G | request-body gzip in the proxy | not run: a candidate ranked before it passed | | | | | | | | |
| E1 | `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` | holds | true | 2774.5 | 2317.5 | 457.0 | false | [2435.25, 2774.5, 3125.75] | [2029.75, 2317.5, 2751.5] | 318.0 |
| C | G with E1 | not run: a candidate ranked before it passed | | | | | | | | |
| E2 | forward `anthropic-dispatch-id=v2d` (prototype, with gzip) | holds | true | 2560.5 | 2590.0 | -29.5 | true | [2373.75, 2560.5, 2750.25] | [1713.75, 2590.0, 3033.75] | 220.5 |

E3 counted TTFT ms — proxied: [1974, 2096, 3111, 2635, 2105, 2494, 2387, 3385, 5019, 2805]; direct: [2420, 1999, 2176, 2351, 2317, 3261, 2625, 2748, 3376, 3331]
E3 proxy ttfb_ms: [1247.9, 762.2, 1561.7, 1460.6, 894.0, 859.2, 1206.8, 1908.6, 2201.5, 1389.8]; upstream_conn: [reused x10]

E1 counted TTFT ms — proxied: [2394, 3267, 3182, 2449, 2562, 3107, 2987, 2995, 2515, 2246]; direct: [2762, 2324, 2748, 2313, 1987, 2194, 1738, 2857, 2322, 2044]
E1 proxy ttfb_ms: [1097.1, 2056.5, 2367.3, 1205.9, 1194.5, 1591.8, 1166.4, 1287.9, 1036.2, 850.0]; upstream_conn: [reused x10]

E2 counted TTFT ms — proxied: [2738, 2274, 2524, 2661, 2105, 2787, 2597, 2502, 2862, 2407]; direct: [3152, 2750, 3031, 1883, 1472, 2430, 1777, 1524, 2778, 3042]
E2 proxy ttfb_ms: [997.2, 1046.6, 1259.3, 1146.4, 1314.6, 1530.3, 1221.5, 1173.8, 1510.3, 1169.3]; upstream_conn: [reused x10]

R0 counted TTFT ms — proxied: [2914, 2581, 2847, 2899, 2534, 3419, 2551, 2866, 2566, 2794]; direct: [2383, 2425, 2223, 2779, 2370, 2628, 1915, 2881, 2866, 2758]
R0 proxy ttfb_ms: [1617.4, 1241.8, 1657.9, 1678.7, 1294.7, 2684.7, 1188.0, 1216.9, 1293.3, 1162.1]; upstream_conn: [reused x10]

E3 wire check: the proxied main request carried `eager_input_streaming` in the key set of all eleven tools it sent (`tools:Agent:keys` through `tools:Write:keys`), where the AC1 proxied request had none and no `fine-grained-tool-streaming` beta token; those eleven `tools:*:keys` rows moved to the direct arm's values, and no row was added. The lever did not add a beta token in this session.
E1 wire check: removed `body:diagnostics`, `header:anthropic-dispatch-id`, `header:x-claude-code-request-class`, `system:0:len`, `system:1:cache_control`, `system:2:cache_control`, `system:2:len`, `system:3:cache_control`, `system:count`, the eleven `tools:*:keys` rows, `tools:advisor:keys`, `tools:count` and `tools:names`; added none.
E2 wire check: `header:anthropic-dispatch-id` appeared once with value `v2d` and was the only diff row removed, none added; the prototype's gzip also held (`header:content-encoding` gzip, `body-bytes` raw 24386 against decoded 67692, body valid JSON).

Screen winner: E3

## Confirmation

### Conditions

- Date 2026-10-25, host `mbp`, Claude Code 2.1.310 (the version § Conditions records), account `p1` (by name only), attempt `deadline_at` 2026-10-26T02:14:43Z. Run after a `just build mbp` of the head below; the screen winner is E3.

Attempted head: 1250a968d831d2f5734bc202364162e388108eee

Measured head: 1250a968d831d2f5734bc202364162e388108eee

- Store paths of the rig built from that head: wrapper module `/nix/store/p6zv0k1zsn6b8x7fxz0crmngx80nij3n-claude-accounts-mod`, agent plist `/nix/store/21j65c6xa7dhnrhwncvm2xlm9ngqfsi9-org.nix-community.home.claude-cache-proxy.plist`, launcher `/nix/store/ra815ss9bn1lcxi1v2sg2z3c8smpp2g1-agent-tools-cache-proxy`; the claude binary and interpreter are the paths § Conditions records.
- Harness command line, with no levers: `python3 -I <S>/i438/rig/ttft.py --rig <S>/i438/rig --proxy-log <S>/i438/runs/confirm.log --out <S>/i438/runs/confirm.json`. The built proxy ran on 27391 with its default upstream; the lever came from the built wrapper alone (`CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`, exported by `claude-account` for routed launches).

### Wire check

One `claude -p` session through the built wrapper and built proxy on 27391, with mitmdump on 27392 as upstream, no lever variables set by the session. The E3 wire check holds: the proxied main request carried `eager_input_streaming` in the key set of eleven of its twelve tools (`tools:Agent:keys` through `tools:Write:keys`, all but `DeferredToolPlaceholder`), where the AC1 proxied request had none; no `fine-grained-tool-streaming` beta token appeared, which the check allows. `reduce.py check` removed those eleven `tools:*:keys` rows against AC1 and added none, and the body was valid JSON (`body_json_ok` true). The result is `confirm-wire.json` in scratch.

### Run

| pair | arm | ttft_ms | exit | proxy_lines | proxy ttfb_ms | upstream_conn |
|---|---|---|---|---|---|---|
| warm-up | proxied | 3001 | 0 | 1 | 1432.5 | reused |
| warm-up | direct | 2274 | 0 | 0 | — | — |
| 0 | proxied | 2004 | 0 | 1 | 852.8 | reused |
| 0 | direct | 2318 | 0 | 0 | — | — |
| 1 | direct | 2177 | 0 | 0 | — | — |
| 1 | proxied | 2669 | 0 | 1 | 1481.7 | reused |
| 2 | proxied | 2445 | 0 | 1 | 1159.9 | reused |
| 2 | direct | 1691 | 0 | 0 | — | — |
| 3 | direct | 2076 | 0 | 0 | — | — |
| 3 | proxied | 2462 | 0 | 1 | 1351.0 | reused |
| 4 | proxied | 1873 | 0 | 1 | 1126.4 | reused |
| 4 | direct | 2615 | 0 | 0 | — | — |
| 5 | direct | 3267 | 0 | 0 | — | — |
| 5 | proxied | 3029 | 0 | 1 | 1764.8 | reused |
| 6 | proxied | 2324 | 0 | 1 | 994.4 | reused |
| 6 | direct | 1762 | 0 | 0 | — | — |
| 7 | direct | 2409 | 0 | 0 | — | — |
| 7 | proxied | 3528 | 0 | 1 | 2427.4 | reused |
| 8 | proxied | 1728 | 0 | 1 | 952.2 | reused |
| 8 | direct | 2660 | 0 | 0 | — | — |
| 9 | direct | 1983 | 0 | 0 | — | — |
| 9 | proxied | 2633 | 0 | 1 | 1499.3 | reused |

### Medians

Median TTFT, proxied 2453.5 ms, direct 2247.5 ms; Δ = proxied − direct = 206.0 ms against the +100 ms threshold (D4). The run was valid (twenty counted runs, every exit 0, one proxied `/v1/messages` line per proxied run) and did not pass. It was run once and not repeated (D4).

### Diagnostics

- Quartiles proxied: [1971.25, 2453.5, 2759.0]; direct: [1927.75, 2247.5, 2626.25] (ms).
- Median within-pair difference (proxied − direct): 439.0 ms.
- Proxy ttfb_ms over the ten proxied runs: [852.8, 1481.7, 1159.9, 1351.0, 1126.4, 1764.8, 994.4, 2427.4, 952.2, 1499.3]; upstream_conn: reused on all ten.

### Smoke

Not run: the confirmation did not pass, and the smoke run follows only a pass.

Per-run usage objects are in [cache-proxy-ttft-gap-usage.md](cache-proxy-ttft-gap-usage.md).

Confirmation: failed

The winner's product commits were reverted at 07f57262.

## Verdict

Shipped lever: none

Routing default: opt-in

No lever shipped: the screen winner's confirmation at 1250a968 measured a Δ of 206.0 ms, over the +100 ms bound, so `claude` routes only with `CLAUDE_CACHE_PROXY=1` (AC3). The measurements are § Screens and § Confirmation above.

AC5: not applicable: no undocumented variable or header shipped.

The rule's limits (spec § Decision rule):

- Run 2 of #422 gave Δ = +221.5 ms but a median within-pair difference of +80 ms, and the per-arm interquartile ranges spanned about 0.45–1.0 s.
- One n = 10 run cannot separate a lever's effect from noise at 100 ms.
- With the run count capped and one confirmation, a lever that does nothing must pass twice by chance to ship, and a lever that works can still fail its confirmation.
- AC2's bound is the issue author's, and it stays the verdict.

## Issue 450

Re-measurement for https://github.com/fagenorn/nix-config/issues/450, by the plan .agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.md. The sections above are #438's record and stand as written; this section corrects its method and holds the current measurement.

### Root cause

The 2026-10-26 investigation on Claude Code 2.1.310 (mbp, account `p1`; its full report is reproduced in the issue) found:

- The proxy hop adds no measurable time to first token. Pooled over 130 pairs, proxied minus direct was −63 ms mean (95% CI −182 to +55), and the same request bytes took 1364 ms through the proxy against 1432 ms straight to the API (n = 80).
- Server latency follows the session (`metadata.user_id.session_id`): swapping only the session id moves one request by about ±700 ms. A 10-pair rule then has a noise band of about ±245–300 ms and cannot resolve 100 ms.
- One effect is real. Claude Code sends the `<total_tokens>N tokens left</total_tokens>` line only to api.anthropic.com. Without it the model opened with a thinking block 45–58% of the time, against 5–12% direct, and its first token came 0–580 ms later. `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` restores the identical line on the wire, and routed launches now export it.
- The wrapper's curl-and-jq health probe added 27 ms to every routed launch. The probe now uses bash's `/dev/tcp`.

### Method

#438 decided on 10 pairs, by the difference of the per-arm medians of harness-side TTFT, with one confirmation run, against a noise band of ±245–300 ms; its numbers stand as recorded above. The rule below replaces that method, and it was committed before any timed pair ran:

- Each run is a fresh `claude -p` session launched through the built wrapper: routed with `CLAUDE_CACHE_PROXY` unset, direct with `CLAUDE_CACHE_PROXY=0`, and nothing else different. The order flips each pair. One warm-up pair is discarded, then exactly 100 valid pairs count.
- Per pair, d = (routed `ttft_ms` + p) − direct `ttft_ms`, where `ttft_ms` is the client's own and p is the probe term of § Probe benchmark (AC2).
- The estimate is the median of d. Its 95% CI is a percentile bootstrap over pairs, 10,000 resamples, seed 450. Routed is within the bound when the CI's upper end is ≤ +100 ms, and that alone sets the routing default.
- A pair counts when both runs exit 0 with a `ttft_ms` and a first content block of `thinking`, `redacted_thinking` or `text`, and the routed run has exactly one proxy `/v1/messages` line and the direct run none. An invalid pair is replaced at the end. An 11th invalid pair makes the run invalid; it is rerun once, and a second invalid run means no valid measurement. A usage limit suspends the run, which resumes at the same head after a new warm-up pair. The run is never extended.
- Diagnostics are recorded and never decide.

### Measurement conditions

- Date 2026-10-26, host `mbp`, account `p2` (by name only; p1 was on its weekly usage limit, so the user chose p2, D17), Claude Code 2.1.310 (`/nix/store/4vc9k1b3vwrj5prm2qkfskgx18dx9zlp-claude-code-2.1.310/bin/claude`).
- Built from M: wrapper module `/nix/store/kqrfw8khg9g5rb13l0y5m3y1240fkim3-claude-accounts-mod`, agent plist `/nix/store/v924cqn2kafn6gxhnzkirdv5w62pgic2-org.nix-community.home.claude-cache-proxy.plist`, launcher `/nix/store/fdv6lakxb781l6r9cjkjcxrbjr9hqmjd-agent-tools-cache-proxy`, interpreter `/nix/store/gpx336is4dkbn2f8w7ch59zm0ygbwq4h-python3-3.13.12-env/bin/python3`, CA bundle `/nix/store/xgjp5yg6q98q5gj267ipv9r7qnwzk0a2-nss-cacert-3.123/etc/ssl/certs/ca-bundle.crt`.
- Experiment proxy on 27450: the launcher with `--port 27450 --keepalive` and `SSL_CERT_FILE` as the service sets it. Wire-check runner on 27451. The installed service on 27183 was only listed: its listener's PID was 96038 before the benchmark and 96038 after it.
- Bootstrap seed 450, 10,000 resamples.

Issue 450 measured head: f956ae7ba24c5f8e643bca8d802a02643888f317

### Budget-line wire check

One routed `claude -p` session on the timed command line, through a copy of M's mod pointed at 27451 and the wire-check runner, which logs per request only whether the body contains `<total_tokens>`: 1 of 1 `/v1/messages` requests carried it (body encodings: identity). The line is on the routed wire on Claude Code 2.1.310.

### Probe benchmark (AC2)

`claude-account run` wall time, routed (`CLAUDE_CACHE_PROXY=1`) minus direct (`0`), over 200 pairs per version, with before and after interleaved and both orders flipping each pair. Each run takes the early exec, with `env` standing in for claude and the experiment proxy answering health.

| Version | Launcher | Pairs | Median increment ms | Quartiles ms | IQR ms |
|---|---|---|---|---|---|
| before | `claude-account` at `51e2b7c9` under M's substitutions | 200 | 28.538 | [25.312, 33.328] | 8.016 |
| after | M's built `claude-account` | 200 | 2.18 | [0.437, 4.557] | 4.12 |

AC2 met: after's median increment is below before's, and the routing tests' fail-to-direct cases pass at M.

Issue 450 probe term: 2.2 ms

### Timed run (AC3)

- Command: `python3 -I ttft450.py --mod <S>/i450/mod-27450 --proxy-log <S>/i450/runs/proxy-27450.log --cwd <S>/i450/cwd --head f956ae7b --out <S>/i450/runs/runs.jsonl`, then `python3 -I analyze450.py --probe-ms 2.2`, where `<S>` is the attempt's scratch directory.
- Pairs: 100 valid; 0 invalid and replaced (none). Warm-up attempts: 1. Reruns: none. Suspensions: none.
- The installed service's listener on 27183 had PID 96038 before and 96038 after.

| Statistic | Value |
|---|---|
| Estimate: median of d = (routed `ttft_ms` + p) − direct `ttft_ms` | 9.7 ms |
| 95% CI, percentile bootstrap, 10,000 resamples, seed 450 | [-90.8, 149.2] ms |
| Bound: CI upper end ≤ +100 ms | outside |

Diagnostics, recorded and never deciding:

- `ttft_ms` quartiles: routed [998.8, 1510.5, 1873.2], direct [1008.5, 1513.5, 1744.8] ms. Mean of d: 95.4 ms.
- Thinking-first: routed 0/100, delay n/a ms; direct 1/100, delay 9 ms (a delay is the arm's median `ttft_ms` of thinking-first runs minus text-first runs, `n/a` when either set is empty).
- Paired medians, routed − direct: harness wall TTFT -27.0 ms; startup (wall TTFT − `ttft_ms`) 29.7 ms, 95% CI [-42.7, 78.9] ms.
- Proxy `ttfb_ms` quartiles over the routed runs: [941.8, 1450.3, 1823.6] ms.

Per-run rows are in [cache-proxy-ttft-gap-450-runs.md](cache-proxy-ttft-gap-450-runs.md).

Issue 450 timed run: estimate 9.7 ms, 95% CI [-90.8, 149.2] ms, outside the +100 ms bound

### Routing verdict

Issue 450 routing default: opt-in

The CI's upper end, 149.2 ms, is over the +100 ms bound, so routing stays opt-in with CLAUDE_CACHE_PROXY=1 (AC4). The budget-line export and the `/dev/tcp` probe ship either way.
