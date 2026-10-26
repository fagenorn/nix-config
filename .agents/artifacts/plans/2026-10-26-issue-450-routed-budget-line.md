# Routed budget line, cheaper probe and re-measured routing default Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Routed `claude` launches carry the first-party `<total_tokens>` budget line again and probe the proxy without curl or jq; a 100-pair paired measurement of that code, made with a bootstrap CI, then sets the routing default.

**Architecture:** Tasks 1–3 change `route_cache_proxy` in `claude-account` one concern at a time: the reminder export, the `/dev/tcp` probe and the default-on switch, each with its routing tests and wording. The switch is a revertible candidate (D3, D4). Task 4 builds that reviewed head M, gates its version, shows the budget line on the routed wire, measures the probe and commits the method. Task 5 runs the 100-pair timed run at M and writes the verdict, both from the same scratch rig rebuilt off `./result`. Everything is recorded in `## Issue 450` of #438's report. Task 6 reads the verdict line and either keeps M's product code or reverts only the switch commit, then fills the last acceptance rows and builds.

**Tech stack:** bash 5.3 (`/dev/tcp`, process substitution), Python 3 standard library (`unittest`, `statistics`, `random`), Nix and home-manager, `just`, `plutil`, `lsof`, `jq`.

Spec: `.agents/artifacts/specs/2026-10-26-issue-450-routed-budget-line-design.md`. This plan cites its `## Decision ledger` by ID: D1–D9 come from design and grill, and D10–D15 were appended by this plan. "438 Dn" cites the #438 spec. Issue: https://github.com/fagenorn/nix-config/issues/450

## Global Constraints

- Base `51e2b7c9` (`origin/main` at planning). Tasks run in index order. Task 4 starts only after Tasks 1–3 have passed their sdd reviews, so review fixes land before M is fixed (D4).
- Files this plan changes, and no others: `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md` (§ Cache proxy), `home/common/claude-code/default.nix` (the comment above `cacheProxyPort` only), `docs/spikes/cache-proxy-ttft-gap.md` (an appended `## Issue 450` plus one pointer line), `docs/spikes/cache-proxy-ttft-gap-450-runs.md` (new), `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` (new).
- Unchanged: `home/linux/claude-local/` (AC5), `python/agent_tools/`, `python/README.md`, `tests/test_claude_code_installed.py`, `docs/spikes/cache-proxy-spike*.md`, `docs/spikes/cache-proxy-ttft-gap-usage.md`, `flake.lock` (no pin move), `CLAUDE.md`, `AGENTS.md`, every skill text. #438's sections of the report stay byte-identical (D9).
- Ports: the experiment proxy uses 27450 and the wire-check proxy 27451 (D6, D7). Never bind, connect to, stop or reconfigure 27183, 8160 or 4322. The only look at 27183 is the read-only listing `lsof -nP -t -iTCP:27183 -sTCP:LISTEN`. If 27450 or 27451 is busy, report BLOCKED with the `lsof -nP -iTCP:<port> -sTCP:LISTEN` output. Never kill a process the task did not start.
- No `just switch`, activation, `launchctl` or `systemctl`. Live runs use the outputs of `./result` from `just build mbp`.
- Account: `CLAUDE_ACCOUNT=p1` by name. Never read its credentials and never switch accounts. A usage limit stops the work at once: report BLOCKED with `blocked_on=usage_limit` (D8, D13).
- No posting to anthropics/claude-code#98464 or any other upstream.
- Scratch: `<S>` is what `launch-scope scratch --repo-root <R> --run-id <I> --worker-id <W>` prints, with the rig under `<S>/i450/`. Nothing under `<S>` is committed. The suspension handoff `$(git rev-parse --git-dir)/issue-450-suspended/` is never committed either (D13).
- Process custody: every live or long command runs in the foreground with an explicit timeout as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, abbreviated `launch-scope exec … --`. A server is started with the Bash tool's `run_in_background: true` around that same prefix, awaited with curl's own `--retry`, and stopped by pid before the step reports. Never `nohup`, `setsid`, `disown` or a `sleep` loop. Commits go through `launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- <git commit args>`; they are signed and end with the session's attribution trailer.
- Measured surface (D4, D15): `home/common/claude-code/accounts/`, `home/common/claude-code/default.nix`, `python/agent_tools/cache_proxy.py` and the `claude-code` node of `flake.lock`. A change after M counts unless every changed line in those paths is a `#` comment or blank. Check: `git diff -U0 "$M" HEAD -- home/common/claude-code/accounts home/common/claude-code/default.nix python/agent_tools/cache_proxy.py | grep -E '^[-+]' | grep -Ev '^(\+\+\+|---) ' | grep -Ev '^[-+][[:space:]]*(#.*)?$'` prints nothing, and `git show "$M:flake.lock" | jq -c '.nodes["claude-code"].locked'` equals the same at `HEAD`. One product change after M is sanctioned (D4): Task 6's opt-in revert, the commit `R=$(git log --no-merges --format=%H -F --grep='revert(issue-450): routing stays opt-in' "$M"..HEAD)`. When `R` is non-empty, the line check runs twice, from `"$M"` to `"$R^"` and from `"$R"` to `HEAD`, instead of once from M; the pin comparison is unchanged. Otherwise run Task 4's, then Task 5's, § Re-measurement.
- `V` is the version that the built `DEFAULT_CLAUDE_BIN` prints (`<V> (Claude Code)`), and `M` is the report's whole line `Issue 450 measured head: <40-hex>` (D14).
- Credential hygiene: before any commit touching `docs/spikes/` or the acceptance record, run for those files `if grep -nE 'sk-ant-|Bearer |oat01' <files>; then exit 1; fi; if grep -nF "$HOME" <files>; then exit 1; fi`.
- Prose that lands in the repository describes the code as it is at that task's commit. A `«fill: …»` slot is replaced in the same task with the value it names: `if grep -rn '«fill' <the task's files>; then exit 1; fi`.
- Focused tests (the targeted file; the repo's tests are `unittest`, and pytest is not installed): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py 2>&1 | tail -n 25` (timeout 600 s; bash on PATH must be ≥ 4.4). `just build mbp`: `launch-scope exec … -- just build mbp` (timeout 3600 s). Final gate (sdd's, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- Wrapper (422 D15, D17; #438; D10): `bash <copy>/bin/claude-account run` from a temporary copy of `home/common/claude-code/accounts` with `CACHE_PROXY_URL=` substituted. The system `env` stands in for claude, the environment is an allowlist, and the real `ProxyServer` answers health (`tests/test_claude_account_routing.py`). D10 adds a copy without curl or jq and a listener that never answers.
- Live (D5–D8, D12): the scratch rig of Tasks 4 and 5 against the outputs of `./result`. Nothing live is committed as a test.
- Build: `just build mbp`, plus CI `Nix Eval` at ship. `tests/test_claude_code_installed.py` is unchanged and not part of this plan's verification.

## Delivery estimate and boundaries

All numbers are estimates.

- Product: `claude-account` +35 lines, routing tests +90, README about +5 sentences, two `default.nix` comment lines.
- Evidence: the report gains 8–12 KB, the runs sibling is 20–30 KB (about 210 rows), and the acceptance record is about 5 KB. Every file stays under the 65,536-byte review-package member limit.
- One review package is expected.
- Wall clock: Tasks 1–3 about 15 min each. Task 4 about 25 min (build, rig, wire check 2 min, benchmark about 2 min). Task 5 about 30 min (rebuild, timed run 15–20 min). Task 6 about 20 min, including its build.
- Ship sync: a merge that changes the measured surface beyond comments needs Task 4's and then Task 5's § Re-measurement, and that run binds (D4, D15). #429 is sequenced after this issue.

## Task index

Task 1 — Budget line on routed launches (AC1) — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md` — full — [task-1.md](2026-10-26-issue-450-routed-budget-line.tasks/task-1.md)
Task 2 — Health probe over bash `/dev/tcp` — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-26-issue-450-routed-budget-line.tasks/task-2.md)
Task 3 — Default-on routing candidate — `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md`, `home/common/claude-code/default.nix` — full — [task-3.md](2026-10-26-issue-450-routed-budget-line.tasks/task-3.md)
Task 4 — Measured head, wire check and probe benchmark (AC2) — `docs/spikes/cache-proxy-ttft-gap.md`, `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md`, and on a version mismatch the comment in `home/common/claude-code/accounts/bin/claude-account` — full — [task-4.md](2026-10-26-issue-450-routed-budget-line.tasks/task-4.md)
Task 5 — Timed run and routing verdict (AC3) — `docs/spikes/cache-proxy-ttft-gap.md`, `docs/spikes/cache-proxy-ttft-gap-450-runs.md`, `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` — full — [task-5.md](2026-10-26-issue-450-routed-budget-line.tasks/task-5.md)
Task 6 — Routing default, record and build (AC4, AC5) — `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md`, and on `opt-in` Task 3's four files — full — [task-6.md](2026-10-26-issue-450-routed-budget-line.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 1 | `tests/test_claude_account_routing.py` under `just agent-workflow-tests`: `assert_routed` requires `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` and `assert_direct` requires it absent; `RoutingTest::test_a_caller_set_reminder_value_is_kept_even_when_empty`, `::test_a_caller_set_endpoint_is_left_alone`, `::test_an_unsubstituted_copy_never_routes`. Task 1 Step 5's gate checks that the comment beside the export names `https://github.com/anthropics/claude-code/issues/98464` and `verified on Claude Code <V>`, each string on its own. Task 4 Step 3 checks `<V>` against the build, and Task 4 Step 5's wire check shows the line on the routed wire |
| AC2 | evidence (classified) | Task 4 | `python3 -I <S>/i450/rig/bench450.py --before <S>/i450/before --after <S>/i450/mod-27450 --proxy-url http://127.0.0.1:27450 --scratch <S>/i450/bench --out <S>/i450/runs/bench.json`, on mbp at M, with M's built proxy on 27450: 200 interleaved pairs per version, routed `CLAUDE_CACHE_PROXY=1` against direct `0`, early exec with `env` for claude (D5, D12). Threshold: a valid run with after's median paired increment below before's, and the routing tests' fail-to-direct cases green. Recorded in report § Probe benchmark (AC2) and acceptance row `AC2` |
| AC3 | evidence (classified) | Task 5 | `python3 -I <S>/i450/rig/ttft450.py --mod <S>/i450/mod-27450 --proxy-log <S>/i450/runs/proxy-27450.log --cwd <S>/i450/cwd --head <M> --out <S>/i450/runs/runs.jsonl`, then `analyze450.py --probe-ms <p>`, on mbp at M with Claude Code ≥ 2.1.310, account `p1`: one warm-up pair, then 100 valid alternating pairs of fresh `claude -p` launches (D6, D8). Threshold: within the bound when the upper end of the 95% bootstrap CI of the median of `(routed ttft_ms + p) − direct ttft_ms` is ≤ +100 ms; the criterion is met once the numbers are recorded in report § Timed run (AC3) and acceptance row `AC3` |
| AC4 | code (classified) | Task 6 | With `Issue 450 routing default: on`: `DefaultRoutingTest` under `just agent-workflow-tests`, plus Task 6 Step 1's docs gate for default-on wording. With `opt-in`: the switch commit reverted, `OptInRoutingTest` under the same suite, and Task 6 Step 4's docs gate for #450's opt-in reason. Row `AC4` |
| AC5 | code (classified) | Task 6 | `just build mbp` exits 0 at the final head; `git diff --quiet 51e2b7c9 HEAD -- home/linux/claude-local` exits 0; CI `Nix Eval` is green on the PR. Row `AC5` |

## Decisions

- Budget-line export, caller-set rule and inheritance: per D1. Probe over `/dev/tcp` with one deadline: per D2, with test seams per D10 and reaping per D11.
- Default-on candidate, opt-out and revert: per D3 and D4. Measured surface, with comment-only changes exempt: per D4 and D15.
- Benchmark: per D5. Timed rig: per D6. Wire check: per D7. Decision rule, validity and stops: per D8, with harness stops and resume per D13.
- The two measuring tasks and their shared rig: per D12. Evidence report, markers and pointer: per D9 and D14.
- Timed-harness custody, timeout, rerun durability and resume of a re-measurement: per D16.

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus; base `51e2b7c9`; no fallback.
- Findings: 5 (4 Blocking, 1 Should fix, 0 Discussion); 5 accepted after verification against the live plan and `python/agent_tools/launch_scope.py`, 0 rejected, 0 deferred. Applied in Task 5's harness, Step 5 and § Resume and in Task 4's § Re-measurement; recorded as D16.

---
