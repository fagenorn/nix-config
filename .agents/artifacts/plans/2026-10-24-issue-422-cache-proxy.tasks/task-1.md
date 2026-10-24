# Task 1: Live-API spike and go/no-go gate

Spec § Spike, per D1, D2, D3, D4, D11, D18 and D19. A throwaway harness in launch scratch records Claude Code's requests through a custom base URL, replays them, and writes the committed report `docs/spikes/cache-proxy-spike.md`. Facts 1, 2 and 4 must all hold; any failure ends the attempt after this task's commit (D1). The harness itself is never committed.

**Files:**
- Create: `docs/spikes/cache-proxy-spike.md`
- Create: `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md`
- Scratch only (never committed): `<scratch>/i422/harness.py`, `<scratch>/i422/results/`, where `<scratch>` is what `launch-scope scratch …` prints

**Interfaces:**
- Consumes: the installed wrapper `/etc/profiles/per-user/anis/bin/claude` (at base it passes a caller-set `ANTHROPIC_BASE_URL` through untouched); `claude-account active` (prints the executing session's account); host `python3` (TLS to `api.anthropic.com` verified at planning).
- Produces, in the report, five machine-readable lines, each alone on its line: `Fact 1: holds|fails`, `Fact 2: holds|fails`, `Fact 4: holds|fails`, `Tool-search switch: ship|drop` (read by Task 3 and Task 4), `Verdict: go|no-go` (read by the controller). A `## Fact 3 — time to first token` section whose body is the single line `Pending: measured on the shipped proxy by Task 5 (D14).` (Task 5 replaces it).
- Produces: the acceptance record with rows `AC1`–`AC6`.

**Invariants:**
- No credential value reaches a file: header values are written only for `anthropic-version`, `anthropic-beta`, `content-type`, `user-agent`, `x-app` and names starting `x-stainless-`; every other header is written by name only. The replay credential is the captured request's header list, held in the harness process's memory (D2).
- Captured bodies stay under `<scratch>/i422/results/bodies/`; the report holds usage objects and metadata, never bodies.
- A replay changes exactly one thing in the captured body bytes: the `max_tokens` value (`re.subn(rb'"max_tokens":\s*\d+', ...)` must report exactly one substitution).
- Every request the harness forwards or sends is in the report's request log with its raw `usage` object (JSON, keys sorted) or its status and first 2 KiB of error body.
- `Verdict: go` only when all three fact lines say `holds`.

- [ ] **Step 1: Confirm the starting state (the check that must flip)**

Run (timeout 30 s): `test ! -e docs/spikes/cache-proxy-spike.md && echo absent`
Expected: `absent`. Then `ACCOUNT="$(claude-account active)"` and record it; it must be a profile name or `default`, not `custom (…)`. Wrapper store path: `readlink -f /etc/profiles/per-user/anis/bin/claude`. Version: `claude --version`.

- [ ] **Step 2: Write the harness `<scratch>/i422/harness.py`**

One standard-library Python file, run as `python3 -I <scratch>/i422/harness.py <phase> --out <scratch>/i422/results --account "$ACCOUNT"` with `<phase>` one of `fact1`, `fact2`, `fact4`, `report` (`report` also takes `--doc docs/spikes/cache-proxy-spike.md` and `--meta <json file>` holding date, host, wrapper path, version, account). Each phase is one process, writes `<out>/<phase>.json` (its verdict inputs) and `<out>/<phase>-requests.jsonl`, and can be rerun alone; `report` only reads those files. Components:

- **Recorder.** `socketserver.ThreadingTCPServer` on `127.0.0.1:0` (`daemon_threads = True`) with an HTTP/1.1 `BaseHTTPRequestHandler` whose `do_GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS` forward to `https://api.anthropic.com` on a fresh `http.client.HTTPSConnection(timeout=600)` per request: request line verbatim, headers in order minus `host`, `connection`, `keep-alive`, `proxy-*`, `te`, `trailer`, `transfer-encoding`, `upgrade` and `accept-encoding`, then `Accept-Encoding: identity` (so the harness can parse usage; recorded in the report's conditions), body bytes verbatim (`Content-Length` as sent). The response streams back as `anthropic-shim.py` does (`read1(65536)`, re-chunk unsized bodies, flush per chunk) while the bytes accumulate for parsing. On completion it appends one record and stores the full request header list in an in-memory dict keyed by `seq`.
- **Record fields:** `seq`, `origin` (`claude` or `replay`), `t` (seconds since the phase start, `time.monotonic()` at send), `method`, `path`, `status`, `header_names` (in order), `headers_kept` (allowlisted values), `model`, `max_tokens`, `thinking` (the body's object or `null`), `marker` (which phase marker the body contains, or `null`), `tools` (count), `tool_search_present` (any tool with `"defer_loading": true` or a `type` starting `tool_search_tool`), `cache_ttls` (every `cache_control` in `tools`, `system` and `messages[*].content[*]`, as its `ttl` or `"5m (default)"`), `usage` (for SSE: `message_start.message.usage` updated key by key with each `message_delta.usage`; for JSON: `usage`), `error_body` (first 2 KiB when `status >= 400`). The body is written to `<out>/bodies/<seq>.json`.
- **`send(seq, body: bytes, path=None) -> record`.** Sends to `https://api.anthropic.com` with the in-memory headers of captured request `seq` minus `host`, `content-length`, `accept-encoding` and hop-by-hop, plus `Accept-Encoding: identity` and the new `Content-Length`; parses and records like the recorder with `origin: "replay"`.
- **`run_claude(prompt, extra_env, extra_args)`.** `subprocess.Popen(["/etc/profiles/per-user/anis/bin/claude", "-p", *extra_args, prompt], cwd=<out>/cwd, env=…)`, env = `os.environ` minus `ANTHROPIC_BASE_URL`, plus `ANTHROPIC_BASE_URL=http://127.0.0.1:<recorder port>`, `CLAUDE_ACCOUNT=<account>` and `extra_env`; bounded by `timeout=600`; returns exit code and stdout.

Phases (thresholds per D3, D4, D19; the account's default model, no `--model`, per D18):

- **`fact1`** (bound 6 min). Run 1: prompt `Reply with exactly: ok`, no extra env. Run 2: the same with `ENABLE_TOOL_SEARCH=true`. Holds iff both exit 0 with `ok` in stdout and every recorded request whose path starts `/v1/messages` has a 2xx status (others recorded with theirs). Per run, the main request is the `/v1/messages` POST with the most tools; record its `anthropic-beta` tokens, tool count, `tool_search_present`, `cache_ttls`. `Tool-search switch: ship` iff run 1's main request has `tool_search_present` false and run 2's true; otherwise `drop`.
- **`fact2`** (bound 12 min). Blocks: `" ".join(f"{tag}-{i:04d}" for i in range(500))` for tags `SPIKE-FACT2-A` and `SPIKE-FACT2-B`; prompt `"<tag>\n<block>\n\nReply with exactly: ok"`. Start A and B concurrently with `extra_args=["--tools", "", "--strict-mcp-config"]` and `FORCE_PROMPT_CACHING_5M=1`. Each session's main request is the first `/v1/messages` POST whose body contains its tag; `t0_A`, `t0_B` are their send times. At `t0_A + 210 s` send A's body with `max_tokens` set to 1. If that replay is not 2xx, fact 2 fails: record its error body, then find the smallest accepted `max_tokens` (the thinking `budget_tokens + 1` when the body has one, else 2, 4, 8 … 4096) for the report's information, and skip the rest. Otherwise at `max(t0_A, t0_B) + 390 s` re-send A's and B's original bodies unchanged. With `P_A = cache_read + cache_creation` of A's original: holds iff the replay and A's re-send each have `cache_read_input_tokens ≥ 0.99·P_A` and `cache_creation_input_tokens ≤ 0.01·P_A`, B's re-send has `cache_creation_input_tokens ≥ 1000`, and each re-send's offset from its own `t0` lies in 360–480 s (outside it, the run is invalid: rerun the phase). Record every request's `cache_creation` 5m/1h split.
- **`fact4`** (bound 8 min). Prompt: `Use the Agent tool twice, one call after the other, both with subagent_type general-purpose. First call: description "alpha", prompt "SPIKE-SIBLING-ALPHA. Reply with exactly: alpha". Second call: description "beta", prompt "SPIKE-SIBLING-BETA. Reply with exactly: beta". Then reply with exactly: done`. Each sibling's first request is the first `/v1/messages` POST whose `messages` has length 1 and whose `messages[0]` contains its marker. Fails (reason recorded) unless both first requests have list-valued `messages[0].content` of equal length differing at exactly one index `D` (the marker block), equal `system` and equal `tools`, and at least one other block. Attachments = every other block, in order. Transform: content = attachments + [block `D`]; the last attachment gets a copy of block `D`'s `cache_control` (or `{"type": "ephemeral"}`); if the body then has more than 4 `cache_control` objects, block `D`'s is removed (moved). Sends, in order, each with `max_tokens` 1 (or the smallest accepted value, found as in `fact2`, per D19): baseline sibling 1, baseline sibling 2, transformed sibling 1, transformed sibling 2. Attachment count: `POST /v1/messages/count_tokens` of `{"model", "messages": [{"role": "user", "content": <attachments without cache_control>}]}` minus the same with content `"."`; if either is refused, the D19 fallback (send transformed sibling 1 with content `[block D]` and subtract totals). Holds iff transformed sibling 2's `cache_read_input_tokens ≥` the count. Record the gain over baseline sibling 2.
- **`report`.** Writes the document: a title `# Cache proxy spike — issue 422`; a run line (date, host `mbp`, Claude Code version, wrapper store path, account, models, `Accept-Encoding: identity` on the upstream leg); the five machine-readable lines; `## Fact 1 — base URL honoured` (both runs' tables and the shape fields, plus the finding that Claude Code documents Remote Control as unavailable behind a non-first-party base URL); `## Fact 2 — replay refreshes the TTL` (timeline table with offsets, `max_tokens`, status and raw usage, then each threshold with its numbers); `## Fact 4 — siblings share attachments` (attachment count and its method, the four sends' usage, the gain); `## Fact 3 — time to first token` with the pending line above; `## Request log` (every record: `seq`, `origin`, method, path, status, header names, kept values, raw usage).

- [ ] **Step 3: Run the phases**

Each in the foreground under `launch-scope exec`, with the timeouts 600 s, 900 s and 600 s:
`python3 -I <scratch>/i422/harness.py fact1 --out <scratch>/i422/results --account "$ACCOUNT"`, then `fact2`, then `fact4`. A phase that fails for an instrument reason (harness bug, invalid timing window, a usage-limit refusal — then set `ACCOUNT` to another signed-in account with headroom from `claude-account status` and record it, per D18) is fixed and rerun alone; a fact that measures `fails` is a result, not a reason to rerun. If fact 1 fails, skip `fact2` and `fact4` and write them `fails` with reason `not run: fact 1 failed`.

- [ ] **Step 4: Write the report and the acceptance record**

Run (timeout 60 s): `python3 -I <scratch>/i422/harness.py report --out <scratch>/i422/results --doc docs/spikes/cache-proxy-spike.md --meta <scratch>/i422/meta.json`.

Create `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` with the heading `# Acceptance record — issue #422` and the table header `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`, one row per criterion `AC1`–`AC6` in issue order, its `Criterion` the issue's criterion text verbatim and its `Check or command` the plan's Acceptance map cell. Fill `AC1`: Observed = the three fact lines and the verdict; Commit = `git rev-parse --short HEAD` at the run; Conditions = account, model, wrapper path; Verdict = `pending fact 3` on go, `not met` on no-go. `AC2`–`AC4`: Observed `in final verification`, Verdict `pending`. `AC5`, `AC6`: Observed `pending Task 5`, Verdict `pending`.

- [ ] **Step 5: Verify**

Run (timeout 60 s) from the worktree root:

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-spike.md
for key in 'Fact 1' 'Fact 2' 'Fact 4'; do grep -Eqx "$key: (holds|fails)" "$f"; done
grep -Eqx 'Tool-search switch: (ship|drop)' "$f"
grep -Eqx 'Verdict: (go|no-go)' "$f"
if grep -qx 'Verdict: go' "$f"; then
  for key in 'Fact 1' 'Fact 2' 'Fact 4'; do grep -qx "$key: holds" "$f"; done
  test "$(grep -c 'cache_read_input_tokens' "$f")" -ge 4
fi
if grep -qx 'Verdict: no-go' "$f" && ! grep -Eq '^Fact [124]: fails$' "$f"; then exit 1; fi
grep -qx 'Pending: measured on the shipped proxy by Task 5 (D14).' "$f"
if grep -nE 'sk-ant-|Bearer |oat01' "$f" .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md; then exit 1; fi
test "$(grep -c '^| AC[1-6] |' .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md)" -eq 6
git status --porcelain --untracked-files=all -- docs .agents/artifacts/plans | grep -v -e 'docs/spikes/cache-proxy-spike.md' -e '2026-10-24-issue-422-cache-proxy.acceptance.md' && exit 1 || true
echo spike-report-ok
```

Expected: `spike-report-ok`. At the starting commit it fails at the first `grep` (no report).

- [ ] **Step 6: Commit, then apply the gate**

```bash
git add docs/spikes/cache-proxy-spike.md .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md
git commit -m "docs(spike): live-API cache proxy spike report (#422)"
```

Then read `Verdict:`. On `go`, report DONE with the verdict and the `Tool-search switch:` value. On `no-go`, report BLOCKED with `spike gate: no-go` and the failing fact names: per D1 nothing else runs, no PR opens, and the issue stays open for the user. Stop every process the harness started before reporting; leave the scratch results in place for review.
