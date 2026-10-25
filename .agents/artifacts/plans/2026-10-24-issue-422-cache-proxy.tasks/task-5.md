# Task 5: Live evidence — time to first token and the A/B eval

Spec § Live evidence, per D14, D18, D20, D24 and D25, with acceptance row `AC1` per D21, D22 and D23. On mbp, the built (never activated) `cache-proxy` service command runs in the foreground as the stand-in for the service, and the built `claude` wrapper goes first on `PATH`. The task measures fact 3 (time to first token, AC6), runs `just evals from-issue 1` with the proxy healthy and then stopped (AC5), records both, and completes acceptance row `AC1`. Order: build, start proxy, TTFT, eval A, stop proxy, eval B, record. Wall-clock bound: about 100 minutes, almost all of it the two eval runs.

**Files:**
- Modify: `docs/spikes/cache-proxy-spike.md` (the `## Fact 3 — time to first token` section)
- Modify (appended by the runs): `home/common/agent-skills/evals/results/results.jsonl`
- Modify: `.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md` (rows `AC1`, `AC5`, `AC6`)
- Scratch only: `<scratch>/i422/evidence/` (proxy logs, scripts, TTFT JSON), `<scratch>` from `launch-scope scratch …`

**Interfaces:**
- Consumes (Task 4, via `./result` after `just build mbp`): the plist `<hash>-org.nix-community.home.claude-cache-proxy.plist` (`ProgramArguments` = `/bin/sh`, `-c`, `/bin/wait4path /nix/store && exec <launcher> --port 27183`; `EnvironmentVariables.SSL_CERT_FILE`), and `<hash>-claude-code-with-accounts-<version>/bin/claude`. Consumes (Task 3): routing (healthy → proxy URL; caller-set `https://api.anthropic.com` → untouched). Consumes (Task 2): the request log lines (`"path":"/v1/messages…"`). Consumes (Task 1): `Tool-search switch:`, the pending fact-3 line, the acceptance record. Consumes (Task 2 Step 0): the report's `Gate ruling: go` line, the gate this task reads instead of the recorded `Verdict:` line (D23). Consumes (controller): the attempt's `deadline_at`, from this task's context file (D24).
- Produces: `Fact 3: holds|fails|human-pending` in the report's fact-3 section; acceptance rows `AC1` (completed), `AC5`, `AC6` filled with observed values, commit and conditions.

**Invariants:**
- No `just switch`, no `launchctl`, no `systemctl` (D14). The only listener on `127.0.0.1:27183` is the process this task starts, and it is stopped before eval B and before the task reports.
- One account for every run: `ACCOUNT="$(claude-account active)"`, exported as `CLAUDE_ACCOUNT` (D18); a usage-limit refusal switches to another signed-in account with headroom from `claude-account status`, recorded in the conditions.
- Proxied and direct TTFT runs differ only in `ANTHROPIC_BASE_URL` (D18).
- Every eval result line stays in `results.jsonl`, including failed attempts; nothing is deleted.
- In the spike report this task replaces only the pending fact-3 line; every recorded line, `Fact 4: fails` and `Verdict: no-go` included, and the `## Gate ruling — 2026-10-25` section stay as they are (D22).

**Deadline cutoff (D20, its deadline source per D24).** The attempt deadline is the `deadline_at` the controller passes in this task's context file; attempt 2's is `2026-10-25T13:29:52Z`. If the context file names none, report NEEDS_CONTEXT at Step 1, before anything runs, and never assume a value. Shipping (review, CI, merge) needs the attempt's last 60 minutes. Before Step 4, Step 5 and Step 6, with `DEADLINE_AT` set to that value, compute the minutes left until `deadline_at − 60 min` (timeout 30 s): `python3 -I -c 'import datetime as d, sys; t = d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")); print(int((t - d.timedelta(minutes=60) - d.datetime.now(d.timezone.utc)).total_seconds() // 60))' "$DEADLINE_AT"`. Step 4 (TTFT, ~10 min) runs only with at least 15 minutes left; each eval step runs only with at least 50 minutes left; there is no instrument rerun past the cutoff. A step skipped by the cutoff is not run at all: its acceptance row gets Observed `not run: attempt deadline cutoff`, the exact command to run in `Check or command`, and Verdict `human-pending`, and the fact-3 line becomes `Fact 3: human-pending` when Step 4 is skipped. Stop the proxy before reporting either way. A `human-pending` row makes sdd's `acceptance_state` `human_pending`, so ship holds the issue open with `needs-verification` instead of closing it.

- [ ] **Step 1: Confirm the starting state**

Run (timeout 30 s): `grep -qx 'Pending: measured on the shipped proxy by Task 5 (D14).' docs/spikes/cache-proxy-spike.md && grep -q '^| AC6 |.*pending Task 5' .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md && echo pending`
Expected: `pending`. The gate must read go (timeout 30 s): `grep -qx 'Gate ruling: go' docs/spikes/cache-proxy-spike.md`; without it, report BLOCKED with `spike gate ruling missing` (D23). Record this task's starting commit (timeout 30 s): `mkdir -p <scratch>/i422/evidence && git rev-parse HEAD > <scratch>/i422/evidence/task5-base`. Then the port must be free (timeout 30 s): `if curl -q --noproxy '*' -s --max-time 1 http://127.0.0.1:27183/_proxy/health; then exit 1; fi`. If something answers, report BLOCKED with `lsof -nP -iTCP:27183 -sTCP:LISTEN`; never kill a process this task did not start.

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
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

wrapper_bin, log, out, switch, cwd = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
if switch not in ("ship", "drop"):  # both arms must get the same switch (D18; Phase-5 review 2 B1)
    sys.exit(f"ttft: invalid tool-search switch {switch!r}")
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
    before, first, requests, usage = proxy_lines(), None, [], None
    start = time.monotonic()
    # Its own process group: the wrapper waits on a separate claude child, so the
    # bound below signals the whole group, not just the wrapper. The group keeps the
    # launch-scope marker in its environment, so custody still covers it.
    proc = subprocess.Popen(ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd,
                            process_group=0)

    def kill_group():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # The whole child lifetime is bounded, a stalled stream included (Phase-5 review S2, review 2 S1).
    watchdog = threading.Timer(300, kill_group)
    watchdog.start()
    try:
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            inner = event.get("event", {}) if event.get("type") == "stream_event" else {}
            if first is None and inner.get("type") == "content_block_delta":
                first = round((time.monotonic() - start) * 1000)
            # Raw usage per API request, kept for AC1 (Phase-5 review B3, review 2 S2):
            # message_start opens a request with its input-side usage, message_delta closes it.
            if inner.get("type") == "message_start":
                requests.append({"start": inner.get("message", {}).get("usage"), "delta": None})
            if inner.get("type") == "message_delta" and requests:
                requests[-1]["delta"] = inner.get("usage")
            if event.get("type") == "result":
                usage = event.get("usage")  # the session total, kept beside the per-request objects
        code = proc.wait()
    finally:
        watchdog.cancel()
        kill_group()  # nothing of this run outlives it, on an exception included
    return {"arm": arm, "ttft_ms": first, "exit": code, "proxy_lines": proxy_lines() - before,
            "requests": requests, "usage": usage}


runs = []
for pair in range(10):
    for arm in (("proxied", "direct") if pair % 2 == 0 else ("direct", "proxied")):
        runs.append(dict(run(arm), pair=pair))
valid = all(r["exit"] == 0 and r["ttft_ms"] is not None and r["usage"] is not None
            and r["requests"] and all(q["start"] is not None and q["delta"] is not None for q in r["requests"])
            and (r["proxy_lines"] >= 1 if r["arm"] == "proxied" else r["proxy_lines"] == 0) for r in runs)
samples = {arm: [r["ttft_ms"] for r in runs if r["arm"] == arm and r["ttft_ms"] is not None]
           for arm in ("proxied", "direct")}
medians = {arm: (statistics.median(v) if v else None) for arm, v in samples.items()}
valid = valid and None not in medians.values()  # an empty arm is an explicit invalid result
delta = medians["proxied"] - medians["direct"] if valid else None
result = {"runs": runs, "valid": valid, "median_ms": medians, "delta_ms": delta,
          "holds": valid and delta <= 100}
out.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: result[k] for k in ("valid", "median_ms", "delta_ms", "holds")}))
```

First read the switch from its one machine-readable line (timeout 30 s); the report also holds a prose line beginning `Tool-search switch:`, so match the whole line, and anything but exactly one match stops the task as BLOCKED with `tool-search switch line missing or duplicated` (Phase-5 review 2 B1): `SWITCH=$(grep -Ex 'Tool-search switch: (ship|drop)' docs/spikes/cache-proxy-spike.md | sed 's/^Tool-search switch: //'); test "$(printf '%s\n' "$SWITCH" | grep -c .)" -eq 1`.
Run (timeout 1500 s), with `CLAUDE_ACCOUNT` exported: `python3 -I <E>/ttft.py "$(cat <E>/wrapper-bin)" <E>/proxy-healthy.log <E>/ttft.json "$SWITCH" <E>/cwd`
Expected: one JSON line with `"valid": true`. An invalid run (a failed launch, a run without a session usage object or with a request lacking either usage object, a proxied run with no proxy line, a direct run with one) is rerun once; still invalid → fact 3 `fails` with the reason recorded.

- [ ] **Step 5: Eval A — proxy healthy (AC5)**

`N0=$(grep -c '"path":"/v1/messages' <E>/proxy-healthy.log)`. Run in the foreground from the worktree root (timeout 3000 s): `PATH="$(cat <E>/wrapper-bin):$PATH" CLAUDE_ACCOUNT="$ACCOUNT" just evals from-issue 1 > <E>/eval-healthy.out 2>&1`; then `N1=` the same count. Record `grep '^VERDICT' <E>/eval-healthy.out`, `N1 - N0` (must be > 0), and `tail -1 home/common/agent-skills/evals/results/results.jsonl | jq -c '{ts, verdict, passed, total, input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens, cost_usd}'`.

- [ ] **Step 6: Stop the proxy, then eval B — proxy stopped (AC5)**

`kill "$(cat <E>/proxy.pid)"`; then the health probe must fail (timeout 30 s): `if curl -q --noproxy '*' -fsS --max-time 1 http://127.0.0.1:27183/_proxy/health; then exit 1; fi`. `N2=$(grep -c '"path":"/v1/messages' <E>/proxy-healthy.log)`. Run (timeout 3000 s): `PATH="$(cat <E>/wrapper-bin):$PATH" CLAUDE_ACCOUNT="$ACCOUNT" just evals from-issue 1 > <E>/eval-stopped.out 2>&1`. Record its `VERDICT` line, the unchanged count (must equal `N2`), and its results line as in Step 5. A run that fails for an instrument reason (usage limit, API outage, timeout) is rerun once and both lines are kept and cited.

- [ ] **Step 7: Record**

In `docs/spikes/cache-proxy-spike.md`, replace the line `Pending: measured on the shipped proxy by Task 5 (D14).` with: the line `Fact 3: holds` or `Fact 3: fails`; the conditions (date, built wrapper and launcher store paths, account, `--model haiku`, `ENABLE_TOOL_SEARCH` as set in both arms, client-side clock from launch to the first `content_block_delta` stream event); a table of the 20 runs (`pair`, `arm`, `ttft_ms`, `exit`, `proxy_lines`) followed by each run's raw per-request usage objects (`requests`: each request's `start` and `delta` usage) and its session `usage` total (Phase-5 review B3 and review 2 S2: AC1 requires the raw usage fields of every request); the two medians and the difference against the +100 ms threshold.

In the acceptance record: `AC6` — Observed: both medians and the difference; Commit: `git rev-parse --short HEAD`; Conditions: as above; Verdict `met` iff fact 3 holds, else `not met`. `AC5` — Observed: each arm's `VERDICT`, proxy-log `/v1/messages` lines added (arm A, > 0) and unchanged (arm B), and each results line's `ts` and token totals; Verdict `met` iff both arms print `VERDICT: PASS` and both counts hold. `AC1` — Observed gains `Gate ruling: go (report § Gate ruling — 2026-10-25)` and `fact 3 recorded (Task 5)`, or `fact 3 human-pending` under the cutoff; Commit: `git rev-parse --short HEAD`. Verdict `met` when the report carries `Fact 1: holds`, `Fact 2: holds`, the recorded `Fact 4:` line, `Gate ruling: go` and a `Fact 3: holds` or `Fact 3: fails` line followed by every run's raw usage, from a TTFT record whose `valid` is true (AC1 asks that the facts are recorded and that the gate holds; AC6 grades fact 3's threshold); `human-pending` when the line is `Fact 3: human-pending`.

- [ ] **Step 8: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-spike.md
a=.agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md
B=$(cat <scratch>/i422/evidence/task5-base)
grep -Eqx 'Fact 3: (holds|fails|human-pending)' "$f"
# AC1's per-request usage (review 2 S2): a met AC1 needs a valid TTFT record, and validity
# includes both usage objects of every request of every run.
if grep '^| AC1 |' "$a" | grep -Eq '\| met \|$'; then
  jq -e '.valid == true and (.runs | length) == 20' <scratch>/i422/evidence/ttft.json > /dev/null
fi
if grep -q 'Pending: measured on the shipped proxy' "$f"; then exit 1; fi
for key in 'Fact 1: holds' 'Fact 2: holds' 'Fact 4: fails' 'Verdict: no-go' 'Gate ruling: go'; do grep -qx "$key" "$f"; done
test "$(git diff --numstat d6b19390 -- "$f" | cut -f2)" = 1
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a"; then exit 1; fi
for row in AC1 AC5 AC6; do
  line=$(grep "^| $row |" "$a")
  if printf '%s' "$line" | grep -Eq 'pending Task 5|pending fact 3'; then exit 1; fi
done
read -r added deleted _ <<<"$(git diff --numstat "$B" -- home/common/agent-skills/evals/results/results.jsonl)"
test "${deleted:-0}" = 0
if ! grep '^| AC5 |' "$a" | grep -q 'human-pending'; then
  test "${added:-0}" -ge 2
fi
if curl -q --noproxy '*' -s --max-time 1 http://127.0.0.1:27183/_proxy/health; then exit 1; fi
echo evidence-recorded
```

Expected: `evidence-recorded`. At the starting commit the first `grep` fails (no fact-3 line). The `results.jsonl` lines are counted from this task's starting commit, so lines that a sync merge from `main` landed before this task never count, and an unchanged file (both evals skipped by the cutoff) passes the deletion check.

- [ ] **Step 9: Commit**

```bash
git add docs/spikes/cache-proxy-spike.md home/common/agent-skills/evals/results/results.jsonl .agents/artifacts/plans/2026-10-24-issue-422-cache-proxy.acceptance.md
git commit -m "docs(spike): fact 3 and the proxy A/B eval runs (#422)"
```

Report DONE with the AC5 and AC6 verdicts (including any `human-pending` from the deadline cutoff); a `not met` verdict is reported as observed, never re-measured until it passes.
