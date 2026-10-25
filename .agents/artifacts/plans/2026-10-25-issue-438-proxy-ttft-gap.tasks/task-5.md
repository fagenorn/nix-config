# Task 5: Confirmation at the final head, smoke run or revert

This task covers spec § Decision rule (confirmation, smoke run, measured surface), per D4, D10 and D11. On mbp it confirms the screen winner once, from the final head's build, with no harness levers. If the confirmation passes, a tool-use smoke run follows. On any other outcome it reverts the winner's product commits, and the opt-in branch (Task 6) ships. This task writes the `Confirmation:` line, report § Confirmation, the usage sibling and acceptance row `AC2`. The same Steps 3–6 are the "new confirmation" that the plan's measured-surface rule calls for.

**Files:**
- Modify: `docs/spikes/cache-proxy-ttft-gap.md` (append `## Confirmation`)
- Create: `docs/spikes/cache-proxy-ttft-gap-usage.md`
- Modify: `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md` (row `AC2`)
- Revert only (Step 7): the winner's commits to `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md`, `python/agent_tools/cache_proxy.py`, `tests/test_cache_proxy.py`, `python/README.md`

**Interfaces:**
- Consumes:
  - the report's whole-line `Screen winner:` and `Missing first-party headers:`;
  - Task 1's `<S>/i438/rig/mkrig.sh`, `session.sh`, `scrub.txt`, `<S>/i438/mitm/addon.py`, `reduce.py` and `ac1-rows.json`;
  - Task 2's `<S>/i438/rig/ttft.py` (`--rig`, `--proxy-log`, `--out`; it prints `{"valid", "median_ms", "delta_ms", "passes"}`);
  - Tasks 3 and 4's commits;
  - the controller's `deadline_at`, from this task's context file (D11).
- Produces the line `Confirmation: <passed|failed|invalid|smoke-failed|deadline-skipped|not-run>`, read by Tasks 6 and 7.

**Invariants:**
- One confirmation run (D4). An invalid run is rerun once. A failed run is never rerun, and no other candidate is tried.
- The run sets no `--proxied-env`: the built wrapper and the built proxy supply the lever.
- Every server this task starts is stopped before it reports. Nothing listens on 27391 or 27392 at the end.
- A revert keeps history (`git revert`), and it restores every reverted path to its content at the screen commit.

**Wire check per winner** (D10, applied to the built product's proxied capture with `reduce.py check`):
- **E3:** `beta-tokens` has a token starting `fine-grained-tool-streaming`, or a `tools:<name>:keys` row contains `eager_input_streaming`.
- **E1:** `added` is empty and `removed` is not, encoding rows aside. It is `vacuous`, and holds, when `ac1-rows.json`'s `rows` minus the encoding rows (`body-encoding`, `header:content-encoding`, `header:content-length`, `header-order`) are empty.
- **G:** `header:content-encoding` is `gzip`, `raw_body_bytes` < `body_bytes`, and `body_json_ok`.
- **C:** both E1's and G's checks.
- **E2:** G's check, plus each `name=value` from `Missing first-party headers:` appears once in `candidate`.

A failure here is a product defect, not a result. Report BLOCKED with `confirmation wire check failed: <fields>` so the controller can route one fix through Task 3 or 4. When this task's context file says that fix already landed, a second failure is `Confirmation: invalid`.

- [ ] **Step 1: Branch gate**

Run (timeout 30 s): `W=$(grep -Ex 'Screen winner: (E3|G|E1|C|E2|none)' docs/spikes/cache-proxy-ttft-gap.md | sed 's/^Screen winner: //'); test "$(printf '%s\n' "$W" | grep -c .)" -eq 1 && if grep -Eq '^Confirmation: ' docs/spikes/cache-proxy-ttft-gap.md; then exit 1; fi && echo "$W"`
- If the check fails, report BLOCKED.
- If it prints `none`: append `## Confirmation`, holding `Not run: no candidate passed its screen (D4).` and the line `Confirmation: not-run`. Fill row `AC2` with Observed `not measured: no candidate passed its screen (report § Screens)`, Commit `git rev-parse --short HEAD` and Conditions `—`. Then go to Step 9.
- Otherwise: with no `deadline_at` in the context file, report NEEDS_CONTEXT. Record `B=$(git log -1 --format=%H -S'Screen winner:' -- docs/spikes/cache-proxy-ttft-gap.md)`, the screen commit.

- [ ] **Step 2: Deadline cutoff**

Run (timeout 30 s): `python3 -I -c 'import datetime as d, sys; t = d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")); print(int((t - d.timedelta(minutes=60) - d.datetime.now(d.timezone.utc)).total_seconds() // 60))' "$DEADLINE_AT"`
Under 15 means `Confirmation: deadline-skipped`. Fill row `AC2` with Observed `not run: attempt deadline cutoff`, keeping Step 5's command in `Check or command`, then go to Step 7.

- [ ] **Step 3: Build the final head and refresh the rig**

Run (timeout 3600 s): `just build mbp`. Then (timeout 120 s): `bash <S>/i438/rig/mkrig.sh "$PWD" <S>/i438/rig && git rev-parse HEAD > <S>/i438/runs/confirm-head`. The refreshed rig must carry the winner:
- **E3:** `grep -c 'export CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1' <S>/i438/rig/mod/bin/claude-account` prints `1`.
- **E1 and C:** `grep -c 'export _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1' …` prints `1`.
- **G, C and E2:** the built launcher's module has gzip: `env -i "$(sed -n 's/^interp //p' <S>/i438/rig/conditions.txt)" -I -c 'import agent_tools.cache_proxy as m; print(m.GZIP_MIN_BYTES)'` prints `4096`.

If the winner is missing, report BLOCKED: Task 3 or Task 4 did not land.

- [ ] **Step 4: Wire check of the built product**

Check that the ports are free (timeout 30 s): `for p in 27391 27392; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done`. If either is busy, report BLOCKED with that output. Start mitmdump with the Bash tool's `run_in_background: true`: `cd <S>/i438/mitm && launch-scope exec … -- devenv -O packages:pkgs "mitmproxy" shell -- mitmdump -q --mode reverse:https://api.anthropic.com --listen-host 127.0.0.1 --listen-port 27392 --set confdir=<S>/i438/mitm/conf -s <S>/i438/mitm/addon.py --set i438_out=<S>/i438/mitm/records/confirm`. Await it: `curl -q --noproxy '*' -s -o /dev/null --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27392/`.

Start the built proxy, also with `run_in_background: true`: `launch-scope exec … -- sh <S>/i438/rig/run-proxy.sh <S>/i438/runs/confirm-wire.log <S>/i438/runs/proxy.pid --upstream http://127.0.0.1:27392`. Await health: `curl -q --noproxy '*' -fsS --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27391/_proxy/health`.

Run one session (timeout 300 s): `launch-scope exec … -- <S>/i438/rig/session.sh <S>/i438/runs/confirm-wire.jsonl CLAUDE_ACCOUNT="$ACCOUNT"`. It carries no lever variables. Stop both servers (`kill "$(cat <S>/i438/runs/proxy.pid)"`, then `kill "$(lsof -nP -t -iTCP:27392 -sTCP:LISTEN)"`). Then run `cd <S>/i438/mitm && python3 -I reduce.py check --against ac1-rows.json --proxied records/confirm --out-json <S>/i438/runs/confirm-wire.json`, apply the winner's wire check, and remove `conf/` and `records/`.

- [ ] **Step 5: The confirmation run (AC2)**

Start the built proxy with `run_in_background: true` and its default upstream: `sh <S>/i438/rig/run-proxy.sh <S>/i438/runs/confirm.log <S>/i438/runs/proxy.pid`. Await health.

Run (timeout 3600 s; about 5 minutes is typical): `launch-scope exec … -- python3 -I <S>/i438/rig/ttft.py --rig <S>/i438/rig --proxy-log <S>/i438/runs/confirm.log --out <S>/i438/runs/confirm.json`

Read the result:
- `"valid": false`: rename the output to `confirm.invalid-1.json` and run once more with a fresh log. Still invalid means `Confirmation: invalid`.
- `"passes": false`: `Confirmation: failed`.
- `"passes": true`: go on to Step 6 with the proxy still running.

In every case except a pass, stop the proxy and go to Step 7.

- [ ] **Step 6: Tool-use smoke run**

Run (timeout 30 s): `printf 'i438-smoke-%s\nsecond line\n' "$(date +%s)" > <S>/i438/cwd/smoke.txt`. Then run (timeout 300 s): `cd <S>/i438/cwd && launch-scope exec … -- env $(sed 's/^/-u /' <S>/i438/rig/scrub.txt) PATH="<S>/i438/rig/bin:$PATH" CLAUDE_ACCOUNT="$ACCOUNT" ENABLE_TOOL_SEARCH=true claude -p --model haiku --output-format stream-json --verbose --allowedTools Read "Use the Read tool to read smoke.txt, then reply with its first line only." > <S>/i438/runs/smoke.jsonl`

The smoke run passes when all of these hold:
- the exit code is 0;
- some `assistant` event holds a `tool_use` block whose `name` is `Read`;
- the `result` event's `result` contains the first line of `smoke.txt`;
- `confirm.log` gained at least two `/v1/messages` request lines during the run.

Stop the proxy. A pass gives `Confirmation: passed`; anything else gives `Confirmation: smoke-failed`.

- [ ] **Step 7: Revert unless passed**

Skip this step on `passed`. Otherwise run (timeout 120 s):

```bash
set -euo pipefail
P=(home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py home/common/claude-code/README.md python/agent_tools/cache_proxy.py tests/test_cache_proxy.py python/README.md)
C=$(git log --no-merges --format=%H "$B"..HEAD -- "${P[@]}")
test -n "$C"
git revert --no-commit $C
git diff --cached --quiet "$B" -- "${P[@]}"
```

`git log` lists the commits newest first, which is the order `git revert` needs. If a revert conflicts, report BLOCKED and leave the tree for the controller. Commit the revert with `git commit -m "revert(issue-438): <W> did not pass its confirmation (<state>)"`, then record `git rev-parse --short HEAD` as the revert commit.

- [ ] **Step 8: Record**

Create `docs/spikes/cache-proxy-ttft-gap-usage.md`. It holds the title `# Cache proxy TTFT gap — confirmation usage (issue 438)`, then one sentence of explanation, then one block per run (the warm-up pair first): `pair`, `arm`, each request's `start` and `delta` usage objects, and the session `usage`, all from `confirm.json` (D10).

Append `## Confirmation` to the report, containing these parts in order:
1. Conditions: the date, `confirm-head` (short), the store paths from `rig/conditions.txt`, the account, `deadline_at`, and the harness command line with no levers.
2. The wire check's result, from `confirm-wire.json`.
3. A pair table `| pair | arm | ttft_ms | exit | proxy_lines | proxy ttfb_ms | upstream_conn |`, with the warm-up pair first and then the 20 counted runs.
4. The two medians, and Δ against the +100 ms threshold.
5. The diagnostics: per-arm quartiles and the median within-pair difference.
6. The smoke result.
7. A link to the usage sibling.
8. The line `Confirmation: <state>`.
9. If a revert was made: `The winner's product commits were reverted at <sha>.`

When Step 5 never ran (`deadline-skipped`, or `invalid` from a second wire-check failure), write only parts 1, 2 (if Step 4 ran), 8 and 9, and create no usage sibling.

Fill row `AC2`:
- Observed: both medians, Δ, the validity, and the smoke result (or the not-run reason).
- Commit: `confirm-head`, short.
- Conditions: as in the section.

- [ ] **Step 9: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; u=docs/spikes/cache-proxy-ttft-gap-usage.md
a=.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
test "$(grep -Ec '^Confirmation: (passed|failed|invalid|smoke-failed|deadline-skipped|not-run)$' "$f")" -eq 1
state=$(sed -n 's/^Confirmation: //p' "$f")
if grep '^| AC2 |' "$a" | grep -q 'pending Task 5'; then exit 1; fi
case "$state" in
  passed) jq -e '.valid and .passes' <S>/i438/runs/confirm.json > /dev/null; test -s "$u" ;;
  not-run) ;;
  *) B=$(git log -1 --format=%H -S'Screen winner:' -- "$f")
     git diff --quiet "$B" HEAD -- home/common/claude-code/accounts python/agent_tools/cache_proxy.py tests/test_cache_proxy.py tests/test_claude_account_routing.py python/README.md home/common/claude-code/README.md ;;
esac
files=("$f" "$a"); test -e "$u" && files+=("$u")
if grep -nE 'sk-ant-|Bearer |oat01' "${files[@]}"; then exit 1; fi
if grep -nF "$HOME" "${files[@]}"; then exit 1; fi
for p in 27391 27392; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done
echo confirmation-recorded
```

Expected: `confirmation-recorded`. At the starting commit the first `grep` fails, because there is no `Confirmation:` line.

- [ ] **Step 10: Commit**

```bash
git add docs/spikes/cache-proxy-ttft-gap.md .agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
test -e docs/spikes/cache-proxy-ttft-gap-usage.md && git add docs/spikes/cache-proxy-ttft-gap-usage.md
git commit -m "docs(issue-438): confirmation of the screen winner"
```

Report DONE with the `Confirmation:` state, both medians and Δ. A failing number is reported as observed and never re-measured (D4).
