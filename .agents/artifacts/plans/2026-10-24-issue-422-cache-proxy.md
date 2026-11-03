# Cache proxy: live-API spike, then pass-through service Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** On the live-API spike's go (Task 1, complete: Claude Code runs through a local proxy and a one-token replay refreshes a cache entry), ship a standard-library pass-through `cache-proxy` as a user service that the `claude` wrapper routes through only when its health check answers.

**Architecture:** Task 1 ran a throwaway recording harness in launch scratch and committed the spike report (`d6b19390`); the owner's ruling makes its gate go (D21), and Task 2 first appends that ruling to the report (D22, D23). A new `agent_tools.cache_proxy` module (one command-table row) forwards bytes verbatim with one keep-alive upstream connection per client connection; `claude-account run` probes `GET /_proxy/health` before every launch; `home/common/claude-code/default.nix` holds the port once and declares a launchd agent (darwin) and a systemd user unit (anis-desktop). Live evidence runs the built, unactivated launcher and wrapper.

**Tech stack:** Python 3 standard library (`socketserver`, `http.server`, `http.client`, `ssl`, `argparse`, `unittest`), bash, Nix (home-manager `launchd.agents`, `systemd.user.services`), `curl`, `jq`, `just`.

Spec: `.agents/artifacts/specs/2026-10-24-issue-422-cache-proxy-design.md`; its `## Decision ledger` rows are cited by ID, D16–D19 appended by this plan, D20 by its standards review, D23–D24 by its amendment after the owner's spike ruling (D21, D22), and D25 by the amended plan's standards review. Issue: https://github.com/fagenorn/nix-config/issues/422

## Global Constraints

- Base: `7601d318` (`origin/main` at planning, still the worktree's merge-base; `origin/main` was `12ce63ef` at the amendment, see § Delivery estimate and boundaries). Tasks 2–5 land in index order; each consumes the earlier ones named in its `Interfaces`.
- **Task 1 is complete at `d6b19390` and is never dispatched; execution starts at Task 2.** Its report records `Fact 1: holds`, `Fact 2: holds`, `Fact 4: fails` and `Verdict: no-go` under the original three-fact gate. The go gate is facts 1 and 2, and both hold (D21). The spike is not re-run and no recorded line of the report is edited (D22). Task 2 Step 0 appends the owner's ruling, and from then on the controller, Task 5 and acceptance row `AC1` read its `Gate ruling: go` line, never the recorded `Verdict:` line (D23). If the recorded facts 1 and 2 do not both hold, Task 2 reports BLOCKED and nothing else runs.
- Files this plan changes, and no others: `docs/spikes/cache-proxy-spike.md` (committed by Task 1; Task 2 appends the ruling, Task 5 fills fact 3), `docs/spikes/cache-proxy-spike-fact3-usage.md` (fact 3's raw usage, moved out of the report after Task 5, D26), `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` (created by Task 1), `python/agent_tools/cache_proxy.py` (new), `tests/test_cache_proxy.py` (new), `tests/test_claude_account_routing.py` (new), `lib/agent-tools.nix`, `python/README.md`, `justfile`, `home/common/claude-code/accounts/bin/claude-account`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `home/common/agent-skills/evals/results/results.jsonl` (appended by the eval runs).
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
- Live (D14, D18, D19): the spike harness (Task 1, complete) and the evidence runs (Task 5).

## Delivery estimate and boundaries

Estimates: 12 repository files. `cache_proxy.py` about 300 lines, `test_cache_proxy.py` about 330, `test_claude_account_routing.py` about 170, the spike report (211 lines, committed) plus the ruling section and fact 3, `claude-account` +30, `default.nix` +45, the READMEs about 20 lines together, the justfile +2, the command table +1, two appended results lines and the acceptance record's `AC1`, `AC5` and `AC6` rows. One review package was expected to fit; after Task 5 the spike report alone (83,987 bytes) exceeded the 65,536-byte review-package member limit, so fact 3's raw usage moved unchanged to `docs/spikes/cache-proxy-spike-fact3-usage.md` (D26). Tasks 2 and 3 are each deliverable alone after Task 1; Task 4 needs both; Task 5 needs Task 4's build. Wall-clock estimate for Task 5 alone: 5 minutes of TTFT plus two eval runs of up to 45 minutes each.

**Base drift (amendment).** `origin/main` moved from `7601d318` to `12ce63ef` after planning, changing six files this plan edits: `home/common/agent-skills/evals/results/results.jsonl` (3 lines appended), `home/common/claude-code/README.md`, `home/common/claude-code/default.nix`, `justfile`, `lib/agent-tools.nix` and `python/README.md`. Every anchor the tasks name still holds at the worktree base and at `12ce63ef`, so no step moves; Task 5's `results.jsonl` gate counts from Task 5's own starting commit, so a sync merge cannot satisfy it (D24). Two ship-sync conflicts are expected: the README § Accounts line that begins `` `default.nix` builds the folder ``, which Task 4 and main both edit (keep main's line and apply Task 4's clause edit to it), and the end of `results.jsonl`, which both append to (keep both sides' lines, main's first).

## Task index

Task 1 — Live-API spike and go/no-go gate — complete at d6b19390, do not dispatch — `docs/spikes/cache-proxy-spike.md`, `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` — full — [task-1.md](2026-10-24-issue-422-cache-proxy.tasks/task-1.md)
Task 2 — Spike gate ruling and the `cache-proxy` command — `docs/spikes/cache-proxy-spike.md`, `python/agent_tools/cache_proxy.py`, `tests/test_cache_proxy.py`, `lib/agent-tools.nix`, `python/README.md`, `justfile` — full — [task-2.md](2026-10-24-issue-422-cache-proxy.tasks/task-2.md)
Task 3 — Health-checked routing in `claude-account run` — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `justfile` — full — [task-3.md](2026-10-24-issue-422-cache-proxy.tasks/task-3.md)
Task 4 — Port binding, wrapper substitution and both services — `home/common/claude-code/default.nix`, `home/common/claude-code/README.md` — full — [task-4.md](2026-10-24-issue-422-cache-proxy.tasks/task-4.md)
Task 5 — Live evidence: time to first token and the A/B eval — `docs/spikes/cache-proxy-spike.md`, `home/common/agent-skills/evals/results/results.jsonl`, `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` — full — [task-5.md](2026-10-24-issue-422-cache-proxy.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 5 | `docs/spikes/cache-proxy-spike.md`, run once by Task 1 (`python3 -I <scratch>/i422/harness.py fact1`, `fact2`, `fact4`, then `report`; committed at `d6b19390` and never re-run, D22) on mbp with the subscription login (D18): the raw usage object of every request in § Request log; the gate per D21 is the recorded `Fact 1: holds` and `Fact 2: holds` lines, read through the appended ruling's `Gate ruling: go` (Task 2 Step 0, D23), with the recorded `Fact 4:` and `Verdict:` lines kept unchanged; fact 3 is Task 5's TTFT run with each run's raw usage, appended to the same report (D14). Task 5 Step 8's script checks all of it (prints `evidence-recorded`) and completes acceptance row `AC1`; the PR links the report |
| AC2 | code | Task 2 | `tests/test_cache_proxy.py` under `just agent-workflow-tests`: `test_sse_events_arrive_byte_identical_and_one_at_a_time`, `test_request_headers_reach_upstream_verbatim_with_only_host_rewritten`, plus the health, 502, mid-stream-reset, reuse and command tests |
| AC3 | code | Task 3 | `tests/test_claude_account_routing.py` under `just agent-workflow-tests` (health up, closed port, foreign 200, caller-set URL, inherited proxy URL with health down, early exec, unsubstituted copy); `claude-local` never receives the URL by construction (D13), its caller-set case pinned by `test_a_caller_set_endpoint_is_left_alone` |
| AC4 | code | Task 4 | `just build mbp` passes; targeted `nix eval` of both darwin agents and the anis-desktop unit match Task 4's `jq` assertions; CI `Nix Eval` (`nixosConfigurations.anis-desktop`) green on the PR (D17) |
| AC5 | evidence | Task 5 | `just evals from-issue 1` with the built wrapper first on `PATH`: `VERDICT: PASS` with the built proxy healthy (proxy log `/v1/messages` lines > 0) and again with it stopped (0 new lines); both runs' `results.jsonl` lines and token totals cited in acceptance row `AC5` (D14, D18) |
| AC6 | evidence | Task 5 | 10 alternating pairs of identical `claude -p` requests on mbp (D18): proxied median TTFT − direct median TTFT ≤ 100 ms; recorded as fact 3 in the spike report and in acceptance row `AC6` |

## Standards review provenance

Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, model gpt-6-astra, effort xhigh), isolated read-only mode, base SHA 7601d3186a03bc2fd363d2c6241ea72925feb835, no focus, no fallback. Findings: B1–B4 blocking, S1–S3 should-fix, D1 and U1 discussion. Accepted and applied: B1 (fact-4 sibling selection excludes the parent), B2 (stage before the first build), B3 (TTFT runs keep raw usage), B4 (AC1 row carries its commands), S1 (explicit 2xx health check + redirect test), S2 (bounded child lifetime, explicit empty-median invalid), S3 (every client write under the client-closed handling + disconnect test), D1 (deadline cutoff in Task 5, per D20). U1 (issue body unreadable from the reviewer sandbox) rejected as a sandbox limit, not a plan defect: the ACs were supplied verbatim. Counts: 8 accepted, 1 rejected, 0 deferred. The amendment after the owner's spike ruling (D21–D24: Task 1 complete, Task 2 Step 0, the `AC1` row, Task 5's gate reads and deadline source) postdates this review.

Second review, of the amended plan at `017acb1c`: Codex (`codex-companion task --fresh --reviewer plan-review`, model gpt-6-astra, effort xhigh), isolated read-only mode, base SHA 7601d3186a03bc2fd363d2c6241ea72925feb835, focus on the amendment's consistency, no fallback. Findings: one blocking, three should-fix, no actionable discussion item. Accepted and applied: B1 (Task 5 reads the tool-search switch from its one whole-line match; the report's prose line made the prefix match two lines), S1 (each TTFT run is its own process group, killed whole at the bound, because the wrapper waits on a separate `claude` child), S2 (TTFT runs keep raw usage per request and AC1's `met` needs a valid record), S3 (the appended ruling names § Fact 3's later replacement as its one exception); D25 records B1, S1 and S2. Counts: 4 accepted, 0 rejected, 0 deferred.

## Decisions

- Spike gate, harness custody, fact definitions: per D1, D2, D3, D4 and D19 (appended), the gate amended by D21 and the report's treatment by D22; the ruling section, its readers and Task 1's completed state per D23 (appended).
- Command contract and forwarding: per D5, D6, D7, D8, refined by D16 (appended).
- Service shape and the port's one home: per D9. Wrapper routing and tool search: per D10, D11, D12. `claude-local`: per D13.
- Live evidence: per D14, refined by D18 (appended); its deadline cutoff per D20, which takes the controller's `deadline_at` per D24 (appended); the TTFT runs' switch read, process-group bound and per-request usage per D25 (appended); fact 3's raw usage in a sibling file per D26 (appended). Test seams: per D15, refined by D17 (appended), which also moves AC4's anis-desktop half to CI.

---
