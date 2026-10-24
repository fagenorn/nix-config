# Task 5: Live evidence — time to first token and the A/B eval

Spec § Live evidence, per D1, D14 and D18. On mbp, the built (never activated) `cache-proxy` service command runs in the foreground as the stand-in for the service, and the built `claude` wrapper goes first on `PATH`. The task measures fact 3 (time to first token, AC6), runs `just evals from-issue 1` with the proxy healthy and then stopped (AC5), and records both. Order: build, start proxy, TTFT, eval A, stop proxy, eval B, record. Wall-clock bound: about 100 minutes, almost all of it the two eval runs.

**Files:**
- Modify: `docs/spikes/cache-proxy-spike.md` (the `## Fact 3 — time to first token` section)
- Modify (appended by the runs): `home/common/agent-skills/evals/results/results.jsonl`
- Modify: `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` (rows `AC1`, `AC5`, `AC6`)
- Scratch only: `<scratch>/i422/evidence/` (proxy logs, scripts, TTFT JSON), `<scratch>` from `launch-scope scratch …`

**Interfaces:**
- Consumes (Task 4, via `./result` after `just build mbp`): the plist `<hash>-org.nix-community.home.claude-cache-proxy.plist` (`ProgramArguments` = `/bin/sh`, `-c`, `/bin/wait4path /nix/store && exec <launcher> --port 27183`; `EnvironmentVariables.SSL_CERT_FILE`), and `<hash>-claude-code-with-accounts-<version>/bin/claude`. Consumes (Task 3): routing (healthy → proxy URL; caller-set `https://api.anthropic.com` → untouched). Consumes (Task 2): the request log lines (`"path":"/v1/messages…"`). Consumes (Task 1): `Tool-search switch:`, the pending fact-3 line, the acceptance record.
- Produces: `Fact 3: holds|fails` in the report's fact-3 section; acceptance rows `AC1` (fact 3 recorded), `AC5`, `AC6` filled with observed values, commit and conditions.

**Invariants:**
- No `just switch`, no `launchctl`, no `systemctl` (D14). The only listener on `127.0.0.1:27183` is the process this task starts, and it is stopped before eval B and before the task reports.
- One account for every run: `ACCOUNT="$(claude-account active)"`, exported as `CLAUDE_ACCOUNT` (D18); a usage-limit refusal switches to another signed-in account with headroom from `claude-account status`, recorded in the conditions.
- Proxied and direct TTFT runs differ only in `ANTHROPIC_BASE_URL` (D18).
- Every eval result line stays in `results.jsonl`, including failed attempts; nothing is deleted.

- [ ] **Step 1: Confirm the starting state**

Run (timeout 30 s): `grep -qx 'Pending: measured on the shipped proxy by Task 5 (D14).' docs/spikes/cache-proxy-spike.md && grep -q '^| AC6 |.*pending Task 5' .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md && echo pending`
Expected: `pending`. Then the port must be free (timeout 30 s): `if curl -q --noproxy '*' -s --max-time 1 http://127.0.0.1:27183/_proxy/health; then exit 1; fi`. If something answers, report BLOCKED with `lsof -nP -iTCP:27183 -sTCP:LISTEN`; never kill a process this task did not start.

- [ ] **Step 2: Build and locate the built service and wrapper**

Run (timeout 3600 s): `just build mbp`. Then (timeout 60 s), with `E=<scratch>/i422/evidence`:

```bash
set -euo pipefail
E=<scratch>/i422/evidence; mkdir -p "$E/cwd"
q() { nix-store --query --requisites ./result | grep -- "$1" || true; }
set -- $(q '-org.nix-community.home.claude-cache-proxy.plist$'); test "$#" -eq 1; PLIST=$1
set -- $(q '-claude-code-with-accounts-[^/]*$'); test "$#" -eq 1; echo "$1/bin" > "$E/wrapper-bin"
python3 -I - "$PLIST" > "$E/run-proxy.sh" <<'EOF'
import plistlib, shlex, sys
with open(sys.argv[1], "rb") as handle:
    agent = plistlib.load(handle)
env = " ".join(f"{k}={shlex.quote(v)}" for k, v in agent["EnvironmentVariables"].items())
argv = " ".join(shlex.quote(a) for a in agent["ProgramArguments"])
print("#!/bin/sh")
print("# The built launchd agent's command and environment, run in the foreground (#422 D14).")
print('echo $$ > "$2"')
print(f'exec env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin {env} {argv} >>"$1" 2>&1')
EOF
chmod +x "$E/run-proxy.sh"; cat "$E/run-proxy.sh"
```

- [ ] **Step 3: Start the proxy (healthy arm)**

Start with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh <E>/run-proxy.sh <E>/proxy-healthy.log <E>/proxy.pid`. Then (timeout 30 s): `curl -q --noproxy '*' -fsS --max-time 2 http://127.0.0.1:27183/_proxy/health` must print `{"service":"cache-proxy","status":"ok"}`, and `head -1 <E>/proxy-healthy.log` must be a `"event":"listening"` line with `"port":27183` and `"upstream":"https://api.anthropic.com"`.

- [ ] **Step 4: Time to first token (AC6, fact 3)**

Save as `<E>/ttft.py`:

```python
"""Ten alternating pairs of identical `claude -p` runs, proxied and direct (#422 D18)."""
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

wrapper_bin, log, out, switch, cwd = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
ARGV = [os.path.join(wrapper_bin, "claude"), "-p", "--model", "haiku", "--output-format", "stream-json",
        "--verbose", "--include-partial-messages", "Reply with exactly: ok"]


def proxy_lines():
    return sum('"path":"/v1/messages' in line for line in log.read_text().splitlines())


def run(arm):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ENABLE_TOOL_SEARCH")}
    env["PATH"] = wrapper_bin + os.pathsep + env["PATH"]
    if switch == "ship":
        env["ENABLE_TOOL_SEARCH"] = "true"
    if arm == "direct":
        env["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"
    before, first = proxy_lines(), None
    start = time.monotonic()
    proc = subprocess.Popen(ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd)
    for line in proc.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if first is None and event.get("type") == "stream_event" \
                and event.get("event", {}).get("type") == "content_block_delta":
            first = round((time.monotonic() - start) * 1000)
    code = proc.wait(timeout=300)
    return {"arm": arm, "ttft_ms": first, "exit": code, "proxy_lines": proxy_lines() - before}


runs = []
for pair in range(10):
    for arm in (("proxied", "direct") if pair % 2 == 0 else ("direct", "proxied")):
        runs.append(dict(run(arm), pair=pair))
valid = all(r["exit"] == 0 and r["ttft_ms"] is not None
            and (r["proxy_lines"] >= 1 if r["arm"] == "proxied" else r["proxy_lines"] == 0) for r in runs)
medians = {arm: statistics.median(r["ttft_ms"] for r in runs if r["arm"] == arm and r["ttft_ms"] is not None)
           for arm in ("proxied", "direct")}
result = {"runs": runs, "valid": valid, "median_ms": medians,
          "delta_ms": medians["proxied"] - medians["direct"],
          "holds": valid and medians["proxied"] - medians["direct"] <= 100}
out.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: result[k] for k in ("valid", "median_ms", "delta_ms", "holds")}))
```

Run (timeout 1500 s), with `CLAUDE_ACCOUNT` exported: `python3 -I <E>/ttft.py "$(cat <E>/wrapper-bin)" <E>/proxy-healthy.log <E>/ttft.json "$(sed -n 's/^Tool-search switch: //p' docs/spikes/cache-proxy-spike.md)" <E>/cwd`
Expected: one JSON line with `"valid": true`. An invalid run (a failed launch, a proxied run with no proxy line, a direct run with one) is rerun once; still invalid → fact 3 `fails` with the reason recorded.

- [ ] **Step 5: Eval A — proxy healthy (AC5)**

`N0=$(grep -c '"path":"/v1/messages' <E>/proxy-healthy.log)`. Run in the foreground from the worktree root (timeout 3000 s): `PATH="$(cat <E>/wrapper-bin):$PATH" CLAUDE_ACCOUNT="$ACCOUNT" just evals from-issue 1 > <E>/eval-healthy.out 2>&1`; then `N1=` the same count. Record `grep '^VERDICT' <E>/eval-healthy.out`, `N1 - N0` (must be > 0), and `tail -1 home/common/agent-skills/evals/results/results.jsonl | jq -c '{ts, verdict, passed, total, input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens, cost_usd}'`.

- [ ] **Step 6: Stop the proxy, then eval B — proxy stopped (AC5)**

`kill "$(cat <E>/proxy.pid)"`; then the health probe must fail (timeout 30 s): `if curl -q --noproxy '*' -fsS --max-time 1 http://127.0.0.1:27183/_proxy/health; then exit 1; fi`. `N2=$(grep -c '"path":"/v1/messages' <E>/proxy-healthy.log)`. Run (timeout 3000 s): `PATH="$(cat <E>/wrapper-bin):$PATH" CLAUDE_ACCOUNT="$ACCOUNT" just evals from-issue 1 > <E>/eval-stopped.out 2>&1`. Record its `VERDICT` line, the unchanged count (must equal `N2`), and its results line as in Step 5. A run that fails for an instrument reason (usage limit, API outage, timeout) is rerun once and both lines are kept and cited.

- [ ] **Step 7: Record**

In `docs/spikes/cache-proxy-spike.md`, replace the line `Pending: measured on the shipped proxy by Task 5 (D14).` with: the line `Fact 3: holds` or `Fact 3: fails`; the conditions (date, built wrapper and launcher store paths, account, `--model haiku`, `ENABLE_TOOL_SEARCH` as set in both arms, client-side clock from launch to the first `content_block_delta` stream event); a table of the 20 runs (`pair`, `arm`, `ttft_ms`, `exit`, `proxy_lines`); the two medians and the difference against the +100 ms threshold.

In the acceptance record: `AC6` — Observed: both medians and the difference; Commit: `git rev-parse --short HEAD`; Conditions: as above; Verdict `met` iff fact 3 holds, else `not met`. `AC5` — Observed: each arm's `VERDICT`, proxy-log `/v1/messages` lines added (arm A, > 0) and unchanged (arm B), and each results line's `ts` and token totals; Verdict `met` iff both arms print `VERDICT: PASS` and both counts hold. `AC1` — Observed gains `fact 3 recorded (Task 5)`; Verdict `met` when the report carries facts 1–4.

- [ ] **Step 8: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-spike.md
a=.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md
grep -Eqx 'Fact 3: (holds|fails)' "$f"
if grep -q 'Pending: measured on the shipped proxy' "$f"; then exit 1; fi
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a"; then exit 1; fi
for row in AC1 AC5 AC6; do
  line=$(grep "^| $row |" "$a")
  if printf '%s' "$line" | grep -q 'pending'; then exit 1; fi
done
test "$(git diff --numstat 7601d318 -- home/common/agent-skills/evals/results/results.jsonl | cut -f2)" = 0
test "$(git diff --numstat 7601d318 -- home/common/agent-skills/evals/results/results.jsonl | cut -f1)" -ge 2
if curl -q --noproxy '*' -s --max-time 1 http://127.0.0.1:27183/_proxy/health; then exit 1; fi
echo evidence-recorded
```

Expected: `evidence-recorded`. At the starting commit the first `grep` fails (no fact-3 line).

- [ ] **Step 9: Commit**

```bash
git add docs/spikes/cache-proxy-spike.md home/common/agent-skills/evals/results/results.jsonl .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md
git commit -m "docs(spike): fact 3 and the proxy A/B eval runs (#422)"
```

Report DONE with the AC5 and AC6 verdicts; a `not met` verdict is reported as observed, never re-measured until it passes.
