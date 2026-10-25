# Routed TTFT gap: measure, then ship the cheapest lever or opt-in routing Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Record how a proxied Claude Code 2.1.302 request differs from a direct one, screen the issue's levers against AC2's +100 ms bound, then ship either the cheapest passing lever, confirmed once at the final head, or `CLAUDE_CACHE_PROXY=1` opt-in routing.

**Architecture:** Tasks 1–2 are live evidence on mbp from the built, never activated outputs. A scratch rig (a wrapper copy and cache-proxy on 27391, mitmdump on 27392) captures both arms for AC1, then R0 and the candidates are screened with #422's harness and the `Screen winner:` line is written. Tasks 3–4 build the winner into `route_cache_proxy`, `agent_tools.cache_proxy` or both. Task 5 confirms it once at the final head or reverts it. Task 6 makes routing opt-in whenever the confirmation did not pass. Task 7 writes the verdict and the record. Each conditional task reads a whole-line marker in the evidence report and does only its branch.

**Tech stack:** bash, Python 3 standard library (`http.client`, `gzip`, `zlib`, `threading`, `unittest`), Nix and home-manager, mitmproxy (devenv ad hoc, scratch only), `curl`, `jq`, `just`.

Spec: `.agents/artifacts/specs/2026-10-25-issue-438-proxy-ttft-gap-design.md`. This plan cites its `## Decision ledger` by ID: D1–D9 come from design and grill, and D10–D13 were appended by this plan. "422 Dn" cites the #422 spec. Issue: https://github.com/fagenorn/nix-config/issues/438

## Global Constraints

- Base `3f4c5072` (`origin/main` at planning). Tasks run in index order. Tasks 3–7 start by reading their branch gate, a whole-line marker in `docs/spikes/cache-proxy-ttft-gap.md` read with `grep -Ex`. Anything but exactly one match is BLOCKED.
- Markers (closed sets, D9): `Missing first-party headers: <name=value[, name=value]…|none>` (Task 1); `Screen winner: <E3|G|E1|C|E2|none>` (Task 2); `Confirmation: <passed|failed|invalid|smoke-failed|deadline-skipped|not-run>` (Task 5); `Shipped lever: <E3|G|E1|C|E2|none>` and `Routing default: <on|opt-in>` (Task 7).
- Files this plan changes, and no others: `docs/spikes/cache-proxy-ttft-gap.md`, `docs/spikes/cache-proxy-ttft-gap-usage.md`, `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md`, `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md`, `python/agent_tools/cache_proxy.py`, `tests/test_cache_proxy.py`, `python/README.md`, `home/common/claude-code/default.nix` (Task 6's comment only).
- Unchanged: `home/linux/claude-local/` (AC4, D6), `docs/spikes/cache-proxy-spike*.md` (D9), `flake.lock`, `CLAUDE.md`, `AGENTS.md`, every skill text. Never touch `.worktrees/worktree-issue-429-orchestrated` or the ledger of orchestration run `rel_01a17264-f4f2-7a51-b489-32d0d6deeb98`.
- Ports (D2): every experiment cache-proxy uses 27391 and mitmdump uses 27392. Ports 27183, 8160 and 4322 are never bound or probed. If 27391 or 27392 is busy when a task starts, the task is BLOCKED with the `lsof -nP -iTCP:<port> -sTCP:LISTEN` output. Never kill a process the task did not start.
- No `just switch`, `launchctl` or `systemctl`. Live runs use `./result` from `just build mbp`.
- One account: `ACCOUNT="$(claude-account active)"`, exported as `CLAUDE_ACCOUNT` for every live run. It is switched only on a usage-limit refusal, and the switch is recorded (422 D18).
- Scratch: `<S>` is what `launch-scope scratch --repo-root <R> --run-id <I> --worker-id <W>` prints. The rig lives in `<S>/i438/rig`, the instrument in `<S>/i438/mitm`, runs in `<S>/i438/runs`, and the session cwd is `<S>/i438/cwd`. If a consumed scratch file is missing (the launch was reaped), the task reports NEEDS_CONTEXT and names the producing task's steps to rerun. Nothing under `<S>` is committed.
- Credential hygiene (D1, 422 D2): before any commit that touches `docs/spikes/` or the acceptance record, run, for those files: `if grep -nE 'sk-ant-|Bearer |oat01' <files>; then exit 1; fi; if grep -nF "$HOME" <files>; then exit 1; fi`. A task that created mitmproxy's `conf/` CA directory or `records/` deletes them before it reports.
- Process custody: every live command runs in the foreground with an explicit timeout, as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`; a task's `launch-scope exec … --` abbreviates that prefix, and `launch-scope scratch …` likewise. A server (a cache-proxy or mitmdump) is started with the Bash tool's `run_in_background: true` around that same `launch-scope exec`. Its readiness is awaited with curl's own `--retry`, and it is stopped by pid before the step reports. Never `nohup`, `setsid`, `disown` or a `sleep` loop. Commits go through `launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- <git commit args>`; they are signed and end with the session's trailers.
- Measured surface (D4): `home/common/claude-code/accounts/`, `home/common/claude-code/default.nix`, `python/agent_tools/cache_proxy.py` and the `claude-code` node of `flake.lock`. After `Confirmation: passed`, any commit touching it needs one new confirmation (Task 5 Steps 3–6), and that run binds.
- `agent_tools` code is standard library only, starts nothing at import time, and follows `docs/standards/agent-helpers.md` rules 1–5.
- Prose that lands in the repository describes the code as it is at that task's commit. A `«fill: …»` slot in a dictated sentence is replaced with the value it names from the evidence report. No slot survives a commit: `if grep -rn '«fill' <the task's files>; then exit 1; fi`.
- Focused tests: `env PYTHONPATH="$PWD/python" python3 -m unittest -v <file>` (timeout 600 s). `just build mbp`: timeout 3600 s. Final gate (sdd's, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- Wrapper (D6, D8, D13; 422 D15, D17): `bash <copy>/bin/claude-account run` from a temporary copy of `home/common/claude-code/accounts` with `CACHE_PROXY_URL=` substituted. `CLAUDE_BIN` is the system `env`, the environment is scrubbed, `HOME` and `CLAUDE_ACCOUNTS_DIR` are temporary, and the real `ProxyServer` answers health (`tests/test_claude_account_routing.py`).
- Proxy (D7, D12; 422 D15, D16): an in-process `cache_proxy.ProxyServer` on port 0 against `FakeUpstream`, which records the raw head and body of each request (`tests/test_cache_proxy.py`).
- Live (D1–D4, D10, D11): the scratch rig, the capture and the harness against `./result`. Nothing live is committed as a test.
- Build: `just build mbp`, plus CI `Nix Eval` at ship.

## Delivery estimate and boundaries

All numbers are estimates.

- Evidence: the report is 25–45 KB and new. The usage sibling is about 25 KB and new. The acceptance record is about 6 KB. Each new file stays under the 65,536-byte review-package member limit, which is why the usage file is always a sibling (D10, 422 D26).
- Pass branch: `claude-account` +10 lines, routing tests +60, README +2 sentences; or `cache_proxy.py` +80, proxy tests +170, two `python/README.md` sentences and one clause in `home/common/claude-code/README.md`.
- Opt-in branch: `claude-account` +12, routing tests +70, one `default.nix` comment, a README rewrite.
- One review package is expected.
- Wall clock: Task 1 about 30 min (including devenv's first mitmproxy fetch), Task 2 about 10 min per screen (at most six screens), Task 5 about 25 min including its build.
- Ship sync: a merge that moves the `claude-code` pin, or brings #429's `cache_proxy.py` changes, touches the measured surface after a passed confirmation and needs a new one (D4). #429 overlaps are resolved at merge (spec § Coordination with #429).

## Task index

Task 1 — Experiment rig and the AC1 capture — `docs/spikes/cache-proxy-ttft-gap.md`, `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md` — full — [task-1.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-1.md)
Task 2 — Lever screens and the winner — `docs/spikes/cache-proxy-ttft-gap.md` — full — [task-2.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-2.md)
Task 3 — Wrapper lever (winner E3, E1 or C) — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md` — full — [task-3.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-3.md)
Task 4 — Proxy gzip and header restore (winner G, C or E2) — `python/agent_tools/cache_proxy.py`, `tests/test_cache_proxy.py`, `python/README.md`, `home/common/claude-code/README.md` — full — [task-4.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-4.md)
Task 5 — Confirmation at the final head, smoke run or revert — `docs/spikes/cache-proxy-ttft-gap.md`, `docs/spikes/cache-proxy-ttft-gap-usage.md`, `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md`, and on a revert Task 3's or Task 4's files — full — [task-5.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-5.md)
Task 6 — Opt-in routing switch (AC3) — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md` — full — [task-6.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-6.md)
Task 7 — Verdict, record and build — `docs/spikes/cache-proxy-ttft-gap.md`, `home/common/claude-code/README.md`, `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md` — low-risk — [task-7.md](2026-10-25-issue-438-proxy-ttft-gap.tasks/task-7.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 1 | On mbp, pinned 2.1.302: two direct sessions (mitmdump through `HTTPS_PROXY` and `NODE_EXTRA_CA_CERTS`, caller-set `https://api.anthropic.com`) and two proxied sessions (stock built proxy on 27391 with mitmdump in reverse mode on 27392 as upstream), all on the timed command line (D1, D10). Threshold: report § AC1 holds the header rows, the beta-token difference, the body-structure rows, the body-encoding row marked derived, and both `Missing first-party headers` lines. Acceptance row `AC1` |
| AC2 | evidence (classified) | Task 5 | `python3 -I <S>/i438/rig/ttft.py` with no levers, the built proxy on 27391 and the wrapper copied from the final head's build: one warm-up pair plus 10 alternating pairs, `--model haiku` (D3, D4). Threshold: a valid run with median proxied − median direct ≤ 100 ms, then a passing tool-use smoke run. Recorded in report § Confirmation and acceptance row `AC2`. With no winner, the row records that nothing was measured |
| AC3 | code (classified) | Task 6 | With `Routing default: opt-in`: `tests/test_claude_account_routing.py` `OptInRoutingTest` under `just agent-workflow-tests`, plus the reason in report § Verdict. With `Confirmation: passed`: not triggered, recorded in row `AC3` |
| AC4 | code (classified) | Task 7 | `just build mbp` exits 0 at the final head; `git diff --quiet 3f4c5072 HEAD -- home/linux/claude-local` exits 0; CI `Nix Eval` is green on the PR |
| AC5 | code (classified) | Task 7 | Shipped lever E1 or C: a grep gate for the comment beside the export in `claude-account` naming `https://github.com/anthropics/claude-code/issues/98464` and `verified on Claude Code 2.1.302`. E2: the same gate beside `FIRST_PARTY_HEADERS` in `cache_proxy.py`. Otherwise row `AC5` reads `not applicable: no undocumented variable or header shipped` |

## Decisions

- Capture instrument and diff: per D1, refined by D10. Rig, ports and prototypes: per D2. Harness changes: per D3.
- Decision rule, cost rank, confirmation, smoke run and measured surface: per D4. Wire-check semantics: per D10. Deadline cutoff: per D11.
- TLS interception, written only: per D5. Wrapper levers: per D6. Proxy gzip and header restore: per D7, with details per D12.
- Opt-in switch and the service: per D8, with its check order per D13. Evidence report, markers and the unedited #422 record: per D9.

---
