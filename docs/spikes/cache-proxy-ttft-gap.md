# Cache proxy: the routed time-to-first-token gap — issue 438

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
| body-bytes | raw 69521, decoded 69521 | raw 67692, decoded 67692 |
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

Beta tokens only direct: cache-diagnosis-2026-04-07, message-threads-2026-08-12, mid-conversation-system-clear-at-2026-08-21, prompt-caching-scope-2026-01-05, thinking-binding-controls-2026-08-01
Beta tokens only proxied: none
Within-arm varying rows: header:x-claude-code-prompt-id, header:x-claude-code-session-id, header:x-client-request-id, usage:cache_creation, usage:cache_creation_input_tokens, usage:cache_read_input_tokens

Lines only in the direct arm's first session:
~~~~
x-anthropic-billing-header: cc_version=2.1.310.754; cc_entrypoint=sdk-cli; cch=7b324; cc_prompt_id=ec928bef-e1d8-471d-87e5-b37765bf2624; cc_turn_origin=sdk; cc_prompt_index=0; cc_turn_index=1;
 - If the user asks about "ultrareview" or how to run it, explain that /code-review ultra launches a multi-agent cloud review of the current branch (or /code-review ultra <PR#> for a GitHub PR); /ultrareview is a deprecated alias for the same command. It is user-triggered and billed; you cannot launch it yourself, so do not attempt to via Bash or otherwise. It needs a git repository (offer to "git init" if not in one); the no-arg form bundles the local branch and does not need a GitHub remote.
<total_tokens>15000000 tokens left</total_tokens>
WebSearch takes a `mode`. Use "standard" by default: it is the normal search, quick and cheap. Use "extended" only when a "standard" result comes back thin, off-target or possibly outdated, or from the start for hard-to-find or niche facts, very recent events, prices and availability, and multi-step research: it is thorough and fresh but several times the cost. When you plan several searches, send them in the same turn.
~~~~

Lines only in the proxied arm's first session:
~~~~
x-anthropic-billing-header: cc_version=2.1.310.754; cc_entrypoint=sdk-cli;
~~~~

Missing first-party headers: anthropic-dispatch-id=v2d
Missing first-party headers without a recorded value: connection, x-claude-code-request-class

## TLS interception (written evaluation)

`HTTPS_PROXY` with a locally trusted interception CA keeps `api.anthropic.com` as the base URL, so the request keeps its first-party shape and Remote Control stays available, but the client's gzip gate turns compression off. The AC1 direct sessions above are exactly such runs: they differ from a plain direct launch in the body-encoding row, which shows identity here where a plain direct launch sends this body gzipped, and this evidence does not isolate any other row that the interception changes. It is not shipped, because a locally trusted CA would intercept the user's OAuth traffic on every launch (D5).
