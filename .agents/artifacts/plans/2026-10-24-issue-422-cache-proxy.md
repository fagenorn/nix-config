# Cache proxy: live-API spike, then pass-through service Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Prove on the live API that Claude Code can run through a local proxy whose replays refresh and reorders share cache entries, then ship a standard-library pass-through `cache-proxy` as a user service that the `claude` wrapper routes through only when its health check answers.

**Architecture:** Task 1 is a throwaway recording harness in launch scratch that writes a committed spike report and decides go/no-go. On go, a new `agent_tools.cache_proxy` module (one command-table row) forwards bytes verbatim with one keep-alive upstream connection per client connection; `claude-account run` probes `GET /_proxy/health` before every launch; `home/common/claude-code/default.nix` holds the port once and declares a launchd agent (darwin) and a systemd user unit (anis-desktop). Live evidence runs the built, unactivated launcher and wrapper.

**Tech stack:** Python 3 standard library (`socketserver`, `http.server`, `http.client`, `ssl`, `argparse`, `unittest`), bash, Nix (home-manager `launchd.agents`, `systemd.user.services`), `curl`, `jq`, `just`.

Spec: `.agents/artifacts/specs/2026-10-24-issue-422-cache-proxy-design.md`; its `## Decision ledger` rows are cited by ID, D16–D19 appended by this plan. Issue: https://github.com/fagenorn/nix-config/issues/422

## Global Constraints

- Base: `7601d318` (`origin/main` at planning). Tasks land in index order; each later task consumes the earlier ones named in its `Interfaces`.
- **Task 1 is a hard gate (D1).** A report whose `Verdict:` line is `no-go` ends the attempt after Task 1's commit: Tasks 2–5 are not started, no PR is opened, the issue stays open for the user, and the controller's report names the failed fact(s).
- Files this plan changes, and no others: `docs/spikes/cache-proxy-spike.md` (new), `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` (new), `python/agent_tools/cache_proxy.py` (new), `tests/test_cache_proxy.py` (new), `tests/test_claude_account_routing.py` (new), `lib/agent-tools.nix`, `python/README.md`, `justfile`, `home/common/claude-code/accounts/bin/claude-account`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `home/common/agent-skills/evals/results/results.jsonl` (appended by the eval runs).
- Unchanged: `home/linux/claude-local/` (D13), `CLAUDE.md`, `AGENTS.md`, every skill text; no instruction ceiling moves.
- `agent_tools` code is standard library only, starts nothing at import time, and follows `docs/standards/agent-helpers.md` rules 1, 2, 3 and 5 (one command-table row; thin shell with `prog="cache-proxy"`; no `sys.path`/`importlib`/`__file__` lookups; tests run `python -m agent_tools.cache_proxy` from source).
- The port `27183` and the URL `http://127.0.0.1:27183` exist only in `home/common/claude-code/default.nix` (D5, D9). Tests choose their own ports.
- No agent runs `just switch` or any activation; live evidence uses the built outputs (D14).
- The spike harness, captured bodies and replay credentials never leave launch scratch; before any commit that touches `docs/spikes/`, `if grep -nE 'sk-ant-|Bearer |oat01' docs/spikes/cache-proxy-spike.md; then exit 1; fi` must pass (D2).
- Every long command, each test run included, runs in the foreground from the worktree root with an explicit timeout above its duration. A worker whose brief carries a `Lifecycle worker:` line runs it as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, creates scratch only under the path `launch-scope scratch …` prints, and commits through `launch-commit … -- <git commit args>`; commits are signed and end with the session's trailers.
- A long-lived process a task starts (the harness's `claude` children, the evidence proxy) is started with the Bash tool's `run_in_background: true` or inside `launch-scope exec`, never `nohup`/`setsid`/`disown`, and is stopped before the task reports.
- Prose that lands in the repository describes the code as it behaves at that task's commit.
- Focused tests: `env PYTHONPATH="$PWD/python" python3 -m unittest -v <file>` (timeout 600 s). `just build`: timeout 3600 s.
- Final gate (sdd's, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- Proxy in-process (D15, D16): `agent_tools.cache_proxy.ProxyServer` on port 0 against `FakeUpstream`, a threaded loopback server in `tests/test_cache_proxy.py` that records raw requests per upstream connection and runs a scripted responder.
- Proxy command (D15): `python -m agent_tools.cache_proxy --port 0 --upstream http://127.0.0.1:<fake>` as a subprocess; port read from the `listening` line.
- Wrapper (D15, D17): `bash <copy>/bin/claude-account run` from a temporary copy of `home/common/claude-code/accounts` with `CACHE_PROXY_URL=` substituted as the build substitutes it, `CLAUDE_BIN` = the system `env`, scrubbed environment, temporary `HOME` and `CLAUDE_ACCOUNTS_DIR`.
- Nix (D17): `just build mbp`; targeted `nix eval` of the two darwin agents and the anis-desktop unit; CI `Nix Eval` at ship.
- Live (D14, D18, D19): the spike harness (Task 1) and the evidence runs (Task 5).

## Delivery estimate and boundaries

Estimates: 12 repository files. `cache_proxy.py` about 300 lines, `test_cache_proxy.py` about 330, `test_claude_account_routing.py` about 170, the spike report about 200 lines of tables and usage JSON, `claude-account` +30, `default.nix` +45, the READMEs about 20 lines together, the justfile +2, the command table +1, two appended results lines and a new acceptance record. One review package is expected to fit. Tasks 2 and 3 are each deliverable alone after Task 1; Task 4 needs both; Task 5 needs Task 4's build. Wall-clock estimate for Task 5 alone: 5 minutes of TTFT plus two eval runs of up to 45 minutes each.

## Task index

Task 1 — Live-API spike and go/no-go gate — `docs/spikes/cache-proxy-spike.md`, `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` — full — [task-1.md](2026-10-24-issue-422-cache-proxy.tasks/task-1.md)
Task 2 — `cache-proxy` command — `python/agent_tools/cache_proxy.py`, `tests/test_cache_proxy.py`, `lib/agent-tools.nix`, `python/README.md`, `justfile` — full — [task-2.md](2026-10-24-issue-422-cache-proxy.tasks/task-2.md)
Task 3 — Health-checked routing in `claude-account run` — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `justfile` — full — [task-3.md](2026-10-24-issue-422-cache-proxy.tasks/task-3.md)
Task 4 — Port binding, wrapper substitution and both services — `home/common/claude-code/default.nix`, `home/common/claude-code/README.md` — full — [task-4.md](2026-10-24-issue-422-cache-proxy.tasks/task-4.md)
Task 5 — Live evidence: time to first token and the A/B eval — `docs/spikes/cache-proxy-spike.md`, `home/common/agent-skills/evals/results/results.jsonl`, `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` — full — [task-5.md](2026-10-24-issue-422-cache-proxy.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 1 | `docs/spikes/cache-proxy-spike.md` on mbp with the subscription login (D18): raw usage object of every request; `Fact 1:`, `Fact 2:`, `Fact 4:` lines each `holds` for `Verdict: go` (thresholds per D3, D4, D19); fact 3 is Task 5's TTFT run, appended to the same report (D1, D14). Task 1 fills acceptance row `AC1`; Task 5 adds fact 3 to it |
| AC2 | code | Task 2 | `tests/test_cache_proxy.py` under `just agent-workflow-tests`: `test_sse_events_arrive_byte_identical_and_one_at_a_time`, `test_request_headers_reach_upstream_verbatim_with_only_host_rewritten`, plus the health, 502, mid-stream-reset, reuse and command tests |
| AC3 | code | Task 3 | `tests/test_claude_account_routing.py` under `just agent-workflow-tests` (health up, closed port, foreign 200, caller-set URL, inherited proxy URL with health down, early exec, unsubstituted copy); `claude-local` never receives the URL by construction (D13), its caller-set case pinned by `test_a_caller_set_endpoint_is_left_alone` |
| AC4 | code | Task 4 | `just build mbp` passes; targeted `nix eval` of both darwin agents and the anis-desktop unit match Task 4's `jq` assertions; CI `Nix Eval` (`nixosConfigurations.anis-desktop`) green on the PR (D17) |
| AC5 | evidence | Task 5 | `just evals from-issue 1` with the built wrapper first on `PATH`: `VERDICT: PASS` with the built proxy healthy (proxy log `/v1/messages` lines > 0) and again with it stopped (0 new lines); both runs' `results.jsonl` lines and token totals cited in acceptance row `AC5` (D14, D18) |
| AC6 | evidence | Task 5 | 10 alternating pairs of identical `claude -p` requests on mbp (D18): proxied median TTFT − direct median TTFT ≤ 100 ms; recorded as fact 3 in the spike report and in acceptance row `AC6` |

## Decisions

- Spike as gate, harness custody, fact definitions: per D1, D2, D3, D4, refined by D19 (appended).
- Command contract and forwarding: per D5, D6, D7, D8, refined by D16 (appended).
- Service shape and the port's one home: per D9. Wrapper routing and tool search: per D10, D11, D12. `claude-local`: per D13.
- Live evidence: per D14, refined by D18 (appended). Test seams: per D15, refined by D17 (appended), which also moves AC4's anis-desktop half to CI.

---
