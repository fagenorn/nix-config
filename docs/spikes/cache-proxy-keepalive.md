# Cache proxy keepalive evidence — issue 423

Run: 2026-10-25 on host mbp; Claude Code 2.1.302; wrapper `/nix/store/yfb2jcxlmwm1bfdsfqrzillw3n0aghmh-claude-code-with-accounts-2.1.302/bin/claude`; launcher `/nix/store/m71c14g6sdi9b93a1nfwn3f3d0lqxdaf-agent-tools-cache-proxy`; account `p1`; code `bba10c48`; model `sonnet`.

AC2: met
AC3: met

## AC2 — keepalive works

| Arm | Session | P handle | Gap (s) | Predecessor context | Measured creation | Ratio | Own share | Subagent deaths in window | P pings (complete, max read) | Threshold | Met |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| off | aeebcaea-8789-4234-9a1f-ee710233929e | 0162c364f9a8 | 489.749 | 135643 | 128140 | 0.9447 | 0.887 | 1 (general-purpose, child dispatch) | 0 (0, n/a) | ratio > 0.50, 1 death | yes |
| on | c21fcf01-7e37-42e2-9dac-44fdc78e3dc2 | fdd4fe4058c1 | 486.844 | 139718 | 451 | 0.0032 | 0.890 | 0 | 1 (1, 139716) | ratio < 0.10, 0 deaths, >= 1 complete 2xx ping with cache_read_input_tokens > 0 | yes |

Measured creation is the measured call's `cache_creation_input_tokens`, and the ratio divides it by the predecessor's context. In the on arm the measured call read 139716 of its 140169 context tokens from cache. In the off arm it read 7960 of 136102.

### Cache report, off arm

```text
Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm read):

agent type       cause           deaths  median gap  premium
---------------  --------------  ------  ----------  -------
general-purpose  child dispatch       1        8.2m       $0

Subagent deaths 1 ($0 premium); main-session deaths 0 ($0)
```

### Cache report, on arm

```text
Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm read):

agent type  cause  deaths  median gap  premium
----------  -----  ------  ----------  -------

Subagent deaths 0 ($0 premium); main-session deaths 0 ($0)
```

The on arm's death table has no rows.

### Proxy log counts

| Arm | Listening line | `/v1/messages` request lines | With `keepalive` | All lines with `keepalive` (not `listening`) | `ping` lines | P handle in a request line |
| --- | --- | --- | --- | --- | --- | --- |
| off | port 60358, no `keepalive` field | 13 | 0 | 0 | 0 | not applicable |
| on | port 61430, `"keepalive":true` | 13 | 13 | 14 | 2 (P: 1, status 200, outcome `complete`, idle_s 272.2, cache_read_input_tokens 139716; C: 1, status 200, outcome `complete`) | yes |

The on arm also logged two `keepalive_end` lines with reason `resumed` (P after 1 ping and 489.2 s idle, C after 1 ping and 482.4 s idle). Each arm's log also holds two `handler_error` lines (`ConnectionResetError`, errno 54), from a client-side reset.

### Windows and cost

| Arm | Window (since, before) | Run start, end (UTC) | Nonce | total_cost_usd |
| --- | --- | --- | --- | --- |
| off | 2026-10-25T17:14:45.165Z, 2026-10-25T17:14:46.165Z | 2026-10-25T17:06:20.382Z, 2026-10-25T17:14:47.995Z | 29c3c11b | 0.7647182 |
| on | 2026-10-25T17:23:33.377Z, 2026-10-25T17:23:34.377Z | 2026-10-25T17:15:09.641Z, 2026-10-25T17:23:35.836Z | eae10ef3 | 0.4313425 |

### Commands

Each proxy: `sh run-proxy.sh <log> <pidfile> <ca bundle> /nix/store/m71c14g6sdi9b93a1nfwn3f3d0lqxdaf-agent-tools-cache-proxy [--keepalive]`, which runs the launcher with `--port 0` under `env -i` with `SSL_CERT_FILE` set to the CA bundle `/nix/store/xgjp5yg6q98q5gj267ipv9r7qnwzk0a2-nss-cacert-3.123/etc/ssl/certs/ca-bundle.crt`.

Each arm: `/nix/store/yfb2jcxlmwm1bfdsfqrzillw3n0aghmh-claude-code-with-accounts-2.1.302/bin/claude -p <prompt> --model sonnet --dangerously-skip-permissions --output-format json`, with `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`, `ENABLE_TOOL_SEARCH=true`, `CLAUDE_ACCOUNT=p1`, `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`, `BASH_DEFAULT_TIMEOUT_MS=600000` and `BASH_MAX_TIMEOUT_MS=600000`. The off arm ran on port 60358 and the on arm on port 61430. The prompt is the plan's, except that child C's command is `python3 -c 'import time; time.sleep(480)'` in place of `sleep 480` (D30). The command is identical in both arms, which differ only in `--keepalive`.

Cache report: `just agent-costs --report cache --projects-dir <arm projects copy> --events-since <window since> --events-before <window before>`.

### Void attempts with `sleep 480` (D30)

The pinned Claude Code 2.1.302 Bash tool refuses a standalone `sleep 480` with `Blocked: standalone sleep 480`. Child C never waited, and both attempts are void with reason `short_wait`. They do not count as the off arm's trial.

| Attempt | Arm | Session | Nonce | Gap (s) | Ratio | Void reason |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | off | 85f5af36-576b-4627-b1f9-14d66501a5d8 | d16778ea | 12.582 | 0.0041 | short_wait |
| 2 (rerun) | off | 3474be6f-93ad-4cf5-8edd-8de00465675c | 8e38b438 | 22.268 | 0.0040 | short_wait |

The on arm was not run with `sleep 480`. The amended command (D30) then got one trial per arm, and neither needed a rerun.

One trial per arm, not tuned (#422 D27).

## AC3 — no regression

| Arm | VERDICT | wall_s | Sessions | Transcript cost | Pings | Ping outcomes | Ping cost | keepalive_end reasons | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| on | PASS (9/9 asserts) | 246 | 1 (041eb2e7-d7ff-4403-9f49-c9eb787be16f, with one subagent transcript) | $1.4483 | 0 | none | $0.0000 | none | $1.4483 |
| off | PASS (9/9 asserts) | 316 | 1 (9c76f317-ef81-40f8-ac86-7e02eb3887de) | $1.6356 | 0 | none | $0.0000 | none | $1.6356 |

The on total is lower than the off total ($1.4483 against $1.6356), so the threshold is met. The on arm sent no ping: its proxy log holds one `listening` line carrying `keepalive: true` and 26 `/v1/messages` `request` lines, every one carrying a `keepalive` field, and no `ping` or `keepalive_end` line. The off arm's log holds one `listening` line without a `keepalive` key and 36 `/v1/messages` `request` lines, none carrying `keepalive`, and no `ping` line. Neither log holds a `handler_error` line. The `keepalive_end` count is zero because each proxy was stopped with `kill` after its eval ended and no conversation had ended earlier.

The two appended `results.jsonl` lines:

| Arm | ts | verdict | wall_s | workdir |
| --- | --- | --- | --- | --- |
| on | 2026-10-25T17:32:50Z | PASS | 246 | `/private/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/eval-from-issue-1.OfAn2F` |
| off | 2026-10-25T17:39:14Z | PASS | 316 | `/private/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/eval-from-issue-1.x1Rsvo` |

### Conditions

Host `mbp`; code `ca015155`; account `p1`; wrapper `/nix/store/yfb2jcxlmwm1bfdsfqrzillw3n0aghmh-claude-code-with-accounts-2.1.302/bin/claude`; launcher `/nix/store/m71c14g6sdi9b93a1nfwn3f3d0lqxdaf-agent-tools-cache-proxy`; `EVAL_TIMEOUT=900`; model `sonnet` (the `EVAL_MODEL` default).

Each proxy: `sh run-proxy.sh <log> <pidfile> <ca bundle> /nix/store/m71c14g6sdi9b93a1nfwn3f3d0lqxdaf-agent-tools-cache-proxy [--keepalive]`, which runs the launcher with `--port 0` under `env -i`, as in AC2. The on arm's launcher got `--keepalive`; the off arm's did not.

Each arm, run from the worktree root with `<port>` the one its proxy's `listening` line named: `env PATH="/nix/store/yfb2jcxlmwm1bfdsfqrzillw3n0aghmh-claude-code-with-accounts-2.1.302/bin:$PATH" ANTHROPIC_BASE_URL="http://127.0.0.1:<port>" ENABLE_TOOL_SEARCH=true CLAUDE_ACCOUNT="p1" EVAL_TIMEOUT=900 just evals from-issue 1`.

Costs: `just agent-costs --format json --days 0 --projects-dir <arm projects copy>`, whose `.strata.claude` reads `cost_basis` `list-price`. An arm's total is its transcripts' `totals.cost_usd` plus its pings' cost priced through `agent_costs.PRICING`, which is zero here.

One trial per arm, never rerun (#422 D27).

`from-issue 1` runs take about 4–6 minutes, so few conversations reach the 270 s due time, and run-to-run variance can exceed the pings' effect. Here the on arm's lower total is variance, not keepalive savings: no ping was sent.
