# Cache proxy keepalive pings for idle subagent conversations Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `cache-proxy --keepalive` replays an idle subagent conversation's last request with `max_tokens=1` while its session is still active, so that its five-minute cache entry survives the wait. The service runs with the flag, and two live A/B runs on mbp measure the effect.

**Architecture:** A new library module, `agent_tools.cache_keepalive`, holds the request classification, the ping builders and the SSE reader (Task 1), and the `Keepalive` state and scheduler (Task 2). `cache_proxy` calls it at one narrow seam: `observe` on the bytes it forwards, then `started`, `chunk` and `done` on the returned track. Task 3 adds that seam together with the `--keepalive` flag, the Nix argument and the docs. Tasks 4 and 5 run the built, unactivated launcher by hand, once with the flag and once without, and record the evidence.

**Tech stack:** Python 3 standard library (`json`, `http.client`, `threading`, `dataclasses`, `unittest`), Nix (home-manager `launchd.agents`, `systemd.user.services`), bash, `jq`, `just`.

Spec: `.agents/artifacts/specs/2026-10-25-issue-423-cache-keepalive-design.md`. Its `## Decision ledger` rows are cited by ID, and this plan appended D23–D26. Issue: https://github.com/fagenorn/nix-config/issues/423

## Global Constraints

- Base: `3f4c5072` (`origin/main` at planning). Tasks land in index order, and each consumes the earlier tasks that its `Interfaces` name.
- Files this plan changes, and no others: `python/agent_tools/cache_keepalive.py` (new), `python/agent_tools/cache_proxy.py`, `tests/test_cache_keepalive.py` (new), `justfile`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `python/README.md`, `docs/spikes/cache-proxy-keepalive.md` (new), `.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md` (new), and `home/common/agent-skills/evals/results/results.jsonl`, which the eval runs append to.
- Unchanged: `CLAUDE.md`, `AGENTS.md`, every skill text, `tests/test_cache_proxy.py` (D25), `lib/agent-tools.nix` (`cache_keepalive` is a library module with no command row, D2), `home/common/claude-code/accounts/`.
- `agent_tools` code is standard library only and starts nothing at import time. It follows `docs/standards/agent-helpers.md` rules 1–5. Strict JSON loads compose the `agent_tools.canonical` hooks, and the conversation handle uses `telemetry_digest` (rule 4).
- No TTL is rewritten. The proxy adds no header of its own and never retries (#422 D6). Header values and bodies are never logged (#422 D8, D11), and bearer tokens stay in process memory (D7).
- #429 edits `cache_proxy.py` in another worktree. Task 3's diff there stays within `ProxyServer.__init__`, the `ProxyHandler` methods it names, two new module functions, `build_parser` and `main`.
- Nobody runs `just switch`, `launchctl` or `systemctl`. Live evidence uses the built outputs (#422 D14, D13).
- A worker whose brief carries a `Lifecycle worker:` line runs every long command, test runs included, as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, in the foreground from the worktree root, with an explicit timeout above its duration. It creates scratch only under the path that `launch-scope scratch …` prints (called `$S` below), and commits through `launch-commit … -- <git commit args>`. Commits are signed and end with the session's trailers.
- A long-lived process (an evidence proxy, a `claude -p` child) starts with the Bash tool's `run_in_background: true` or inside `launch-scope exec`, never with `nohup`, `setsid` or `disown`. It is stopped before the task reports.
- **Deadline (D26; #422 D20, D24).** `DEADLINE_AT` is the `deadline_at` in the task's context from the controller (this attempt: `2026-10-25T19:11:36Z`). With no value there, report NEEDS_CONTEXT before any live run. Minutes left before the cutoff (timeout 30 s): `python3 -I -c 'import datetime as d, sys; t = d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")); print(int((t - d.timedelta(minutes=60) - d.datetime.now(d.timezone.utc)).total_seconds() // 60))' "$DEADLINE_AT"`.
- Before any commit that touches `docs/spikes/` or the acceptance record: `if grep -nE 'sk-ant-|Bearer |oat01' <those files>; then exit 1; fi`.
- Prose that lands in the repository describes the code as it behaves at that task's commit.
- Focused tests (timeout 600 s), from the worktree root: `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py`. Build (timeout 3600 s): `just build`.
- Final gate (sdd's, run once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- Pure functions (D5, D6, D9, D11, D20, D23): `cache_keepalive.classify`, `conversation_handle`, `ping_body`, `ping_headers`, `identity_headers` and `SseReader`, driven directly on bodies, headers and SSE streams shaped like Claude Code's.
- Keepalive on a fake clock (D12): `Keepalive(log, connect, clock)`, with `observe` and the track's `started`/`chunk`/`done` fed directly, `tick` and `send` against #422's `FakeUpstream`, and `run` with `TICK_INTERVAL` patched (D25).
- Proxy in process (#422 D15): `cache_proxy.ProxyServer(0, upstream, log, keepalive=…)` in front of `FakeUpstream`, with raw-socket clients.
- Command: `python -m agent_tools.cache_proxy` as a subprocess.
- Nix (#422 D17): `just build`, plus `nix eval` of both darwin agents' `ProgramArguments` and anis-desktop's `ExecStart`. CI `Nix Eval` covers anis-desktop.
- Live (D13–D15, D26): the runs of Tasks 4 and 5.

## Delivery estimate and boundaries

Estimates: 10 repository files. `cache_keepalive.py` is about 350 lines; `tests/test_cache_keepalive.py` about 700 lines (about 32 KB, the largest member); `cache_proxy.py` about +55/−10; `default.nix` +3; the READMEs about 12 lines together; the report about 8–15 KB; the acceptance record about 3 KB; and two `results.jsonl` lines. One review package is expected to fit, with every member under 64 KiB. Wall clock (estimates): Tasks 1–3 about 60–80 min; Task 4 about 25 min (two arms of about 10 min each); Task 5 about 20 min (two evals of about 5 min each). Task 5 is the task most likely to meet the cutoff and be recorded `human-pending` (D26).

## Task index

Task 1 — Classification, ping building and the SSE reader — `python/agent_tools/cache_keepalive.py`, `tests/test_cache_keepalive.py`, `justfile` — full — [task-1.md](2026-10-25-issue-423-cache-keepalive.tasks/task-1.md)
Task 2 — The `Keepalive` state and scheduler — `python/agent_tools/cache_keepalive.py`, `tests/test_cache_keepalive.py` — full — [task-2.md](2026-10-25-issue-423-cache-keepalive.tasks/task-2.md)
Task 3 — `cache-proxy --keepalive`: the seam, the service flag and the docs — `python/agent_tools/cache_proxy.py`, `tests/test_cache_keepalive.py`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `python/README.md` — full — [task-3.md](2026-10-25-issue-423-cache-keepalive.tasks/task-3.md)
Task 4 — AC2 evidence: the eight-minute parent wait, off then on — `docs/spikes/cache-proxy-keepalive.md`, `.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md` — full — [task-4.md](2026-10-25-issue-423-cache-keepalive.tasks/task-4.md)
Task 5 — AC3 evidence: the A/B pipeline eval, on then off — `docs/spikes/cache-proxy-keepalive.md`, `.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md`, `home/common/agent-skills/evals/results/results.jsonl` — full — [task-5.md](2026-10-25-issue-423-cache-keepalive.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 3 | `tests/test_cache_keepalive.py` under `just agent-workflow-tests`. `ClassifyTest`, `HandleTest`, `PingRequestTest` and `SseReaderTest` (Task 1) cover eligibility and the ping's shape. `KeepaliveTest`, `FailingPingTest` and `RunLoopTest` (Task 2) cover the 270 s ping with a sibling active, no ping before 270 s, `session_idle`, repeats up to the 60-min `ceiling`, the pending-tool rule, mutual idleness, `ttl_1h`/main/`thinking_budget` never pinged, `no_tail_mark`, non-2xx client responses, `ping_failed` without retry, `resumed`, supersession, a streaming candidate, a lone surrogate, eviction and the loop's error lines. `KeepaliveProxyTest` and `KeepaliveCommandTest` (Task 3) cover identity forwarding, a ping that sends no byte to the idle client, the failure seams and the flag |
| AC2 | evidence | Task 4 | Two fresh `claude -p` sessions on mbp, off then on, each through its own built launcher on `--port 0` with a caller-set `ANTHROPIC_BASE_URL` (D13, D14, D26). P's first call after child C's foreground `sleep 480`, from P's isolated transcript copy and `just agent-costs --report cache --projects-dir <copy> --events-since <measured call start> --events-before <start + 1 s>`. Threshold: creation ÷ predecessor context < 0.10 on and > 0.50 off; `Subagent deaths 1` with a `general-purpose`/`child dispatch` row off and `Subagent deaths 0` on; at least one `complete` `ping` line for P's conversation with `cache_read_input_tokens` > 0 on. Acceptance-record row `AC2` |
| AC3 | evidence | Task 5 | `just evals from-issue 1` once per arm on mbp, on first, through the built wrapper and launcher with `EVAL_TIMEOUT=900` (D15, D21, D26). Threshold: the on run prints `VERDICT: PASS`, and its total, `.strata.claude.totals.cost_usd` from `just agent-costs --format json --days 0 --projects-dir <an isolated copy of that eval's transcripts>` plus its `ping` lines priced with `agent_costs.PRICING`, is lower than the off run's. Both appended `results.jsonl` lines are cited. Acceptance-record row `AC3`; an arm past the cutoff is `human-pending` |

## Decisions

- Mechanism and switch: per D1 and D3. Module and seam: per D2, refined by D19 and D24.
- Identity and eligibility: per D4 and D5, with D23 for `unparsed`. Mark enumeration and encoding: per D16 and D20.
- The ping and held credentials: per D6 and D7. Activity and the response tap: per D8 and D9. Timing, stop rules and bounds: per D10. Log contract: per D11. Failure posture: per D18, refined by D24.
- Tests: per D12, with D25 for their placement.
- Evidence: venue per D13; AC2 per D14; AC3 per D15 and D21; the run pins, cutoff and void rules per D26. The accepted cost of pinging finished subagents: per D17 and D22.

---
