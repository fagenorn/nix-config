# Task 2: Lever screens and the winner

This task covers spec § Experiment rig, § Candidates and § Decision rule (screens and winner), per D2, D3, D4, D10, D11 and D16. On mbp it screens R0 and then the candidates in rank order, each with a wire check followed by a timed run. It writes report § Screens with the `Screen winner:` line. No product file changes.

**Files:**
- Modify: `docs/spikes/cache-proxy-ttft-gap.md` (append `## Screens`)
- Scratch only: `<S>/i438/rig/ttft.py`, `<S>/i438/proto/`, `<S>/i438/runs/`, `<S>/i438/mitm/records/`

**Interfaces:**
- Consumes (Task 1):
  - `<S>/i438/rig/` with `bin/claude`, `run-proxy.sh`, `run-prototype.sh`, `session.sh`, `scrub.txt` and `conditions.txt` (its `interp` line);
  - `<S>/i438/mitm/addon.py`, `reduce.py` (the `check` subcommand) and `ac1-rows.json`;
  - the report line `Missing first-party headers: <name=value[, …]|none>`.
- Consumes (controller): the attempt's `deadline_at`, from this task's context file (D11).
- Produces:
  - `<S>/i438/rig/ttft.py`, the harness below, reused by Task 5;
  - `<S>/i438/runs/<X>.json`, the counted timed run of each screened candidate `X`;
  - `<S>/i438/runs/<X>.wire-failed`, written when X's wire check failed twice;
  - `<S>/i438/runs/<X>.skipped`, written when the cutoff skipped X;
  - the report line `Screen winner: <E3|G|E1|C|E2|none>`.

**Invariants:**
- A lever goes on the proxied arm only. The direct arm is identical in every run (D2).
- The order is fixed: R0 first, then E3, G, E1, C, E2. E3, E1 and E2 always run. G runs only if E3 has not passed, and C only if none of E3, G and E1 has passed. When `Missing first-party headers: none`, E2 drops out and G runs unconditionally in its place (spec § Candidates).
- No screen is repeated to get a different result. An invalid timed run is rerun once, and a second invalid run counts as not passing (D4). A wire check that fails again after one rig fix counts as not passing, without timing (D10).
- Timing runs never go through mitmdump. Only the wire-check session does.
- Prototypes stay in scratch and are never committed (D2).

**Deadline cutoff (D11).** If the context file names no `deadline_at`, report NEEDS_CONTEXT at Step 1, before anything runs. Before each candidate, compute the minutes left (timeout 30 s): `python3 -I -c 'import datetime as d, sys; t = d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")); print(int((t - d.timedelta(minutes=60) - d.datetime.now(d.timezone.utc)).total_seconds() // 60))' "$DEADLINE_AT"`. A candidate starts only with at least 70 minutes left. Otherwise write `<S>/i438/runs/<X>.skipped`, record the candidate as `not run: attempt deadline cutoff`, and count it as not passing.

- [ ] **Step 1: Confirm the starting state**

Run (timeout 60 s): `test "$(grep -Ec '^Missing first-party headers: ' docs/spikes/cache-proxy-ttft-gap.md)" -eq 1 && if grep -q '^## Screens$' docs/spikes/cache-proxy-ttft-gap.md; then exit 1; fi && test -x <S>/i438/rig/run-prototype.sh && test -s <S>/i438/mitm/ac1-rows.json && for p in 27391 27392; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done && echo ready`
Expected: `ready`. A missing rig file means NEEDS_CONTEXT: rerun Task 1 Steps 2–3, and then Steps 4–6 without committing, to rebuild `ac1-rows.json`. Set `ACCOUNT="$(claude-account active)"` and `mkdir -p <S>/i438/runs <S>/i438/proto`.

- [ ] **Step 2: The harness**

Save `<S>/i438/rig/ttft.py`. It is #422's task-5 harness with exactly D3's five changes:

```python
"""#438 harness (D3): a warm-up pair, then ten alternating pairs of identical `claude -p` runs."""
import argparse
import json
import os
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

parser = argparse.ArgumentParser(prog="ttft")
parser.add_argument("--rig", required=True, type=Path)
parser.add_argument("--proxy-log", required=True, type=Path)
parser.add_argument("--out", required=True, type=Path)
parser.add_argument("--proxied-env", action="append", default=[], metavar="KEY=VALUE")
args = parser.parse_args()
SCRUB = (args.rig / "scrub.txt").read_text().split()
levers = dict(item.split("=", 1) for item in args.proxied_env)
if not set(levers) <= set(SCRUB):  # an unscrubbed lever could reach the direct arm
    sys.exit(f"ttft: levers outside scrub.txt: {sorted(set(levers) - set(SCRUB))}")
ARGV = [str(args.rig / "bin" / "claude"), "-p", "--model", "haiku", "--output-format", "stream-json",
        "--verbose", "--include-partial-messages", "Reply with exactly: ok"]


def proxy_requests():
    lines = [json.loads(line) for line in args.proxy_log.read_text().splitlines() if line.startswith("{")]
    return [q for q in lines if q.get("event") == "request" and q.get("path", "").startswith("/v1/messages")]


def run(arm):
    env = {k: v for k, v in os.environ.items() if k not in SCRUB}
    env["PATH"] = str(args.rig / "bin") + os.pathsep + env["PATH"]
    env["ENABLE_TOOL_SEARCH"] = "true"  # the same caller-set value in both arms (422 D18)
    if arm == "direct":
        env["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"  # caller-set first-party URL (422 D14)
    else:
        env.update(levers)
    before, first, requests, usage = len(proxy_requests()), None, [], None
    start = time.monotonic()
    proc = subprocess.Popen(ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
                            cwd=args.rig.parent / "cwd", process_group=0)

    def kill_group():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    watchdog = threading.Timer(300, kill_group)  # the whole child lifetime is bounded (422 D25)
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
            if inner.get("type") == "message_start":
                requests.append({"start": inner.get("message", {}).get("usage"), "delta": None})
            if inner.get("type") == "message_delta" and requests:
                requests[-1]["delta"] = inner.get("usage")
            if event.get("type") == "result":
                usage = event.get("usage")
        code = proc.wait()
    finally:
        watchdog.cancel()
        kill_group()
    added = proxy_requests()[before:]
    return {"arm": arm, "ttft_ms": first, "exit": code, "proxy_lines": len(added),
            "proxy": [{k: q.get(k) for k in ("path", "status", "ttfb_ms", "upstream_conn")} for q in added],
            "requests": requests, "usage": usage}


def valid(r):
    return (r["exit"] == 0 and r["ttft_ms"] is not None and r["usage"] is not None and bool(r["requests"])
            and all(q["start"] is not None and q["delta"] is not None for q in r["requests"])
            and (r["proxy_lines"] >= 1 if r["arm"] == "proxied" else r["proxy_lines"] == 0))


def order(pair):
    return ("proxied", "direct") if pair % 2 == 0 else ("direct", "proxied")


warmup = [dict(run(arm), pair="warm-up") for arm in order(0)]  # discarded, but must be valid (D3)
runs = [dict(run(arm), pair=pair) for pair in range(10) for arm in order(pair)]
ok = all(valid(r) for r in warmup + runs)
samples = {arm: [r["ttft_ms"] for r in runs if r["arm"] == arm and r["ttft_ms"] is not None]
           for arm in ("proxied", "direct")}
medians = {arm: (statistics.median(v) if v else None) for arm, v in samples.items()}
ok = ok and None not in medians.values()
delta = medians["proxied"] - medians["direct"] if ok else None
by_pair = {p: {r["arm"]: r["ttft_ms"] for r in runs if r["pair"] == p} for p in range(10)}
within = [d["proxied"] - d["direct"] for d in by_pair.values() if None not in (d.get("proxied"), d.get("direct"))]
diagnostics = {  # recorded, never deciding (D4)
    "quartiles_ms": {arm: (statistics.quantiles(v, n=4) if len(v) > 1 else None) for arm, v in samples.items()},
    "median_within_pair_ms": statistics.median(within) if within else None,
    "proxy_ttfb_ms": [q["ttfb_ms"] for r in runs if r["arm"] == "proxied" for q in r["proxy"]],
    "upstream_conn": [q["upstream_conn"] for r in runs if r["arm"] == "proxied" for q in r["proxy"]]}
result = {"levers": levers, "warmup": warmup, "runs": runs, "valid": ok, "median_ms": medians,
          "delta_ms": delta, "passes": ok and delta <= 100, "diagnostics": diagnostics}
args.out.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: result[k] for k in ("valid", "median_ms", "delta_ms", "passes")}))
```

- [ ] **Step 3: The prototypes (G, and E2 unless it dropped out)**

Save `<S>/i438/proto/make.py`. It runs as `python3 -I make.py <worktree> <out-dir> [name=value…]` and does three things:
1. Copies `<worktree>/python` to `<out-dir>/python`.
2. In the copy's `agent_tools/cache_proxy.py`, asserts that the base `_send_request` method below occurs exactly once and replaces it with the patched one. It also adds `import gzip` after `import argparse`, and `I438_EXTRA = (<the name=value pairs as tuples>,)` after the `UPSTREAM_FAILURES = …` line, with `()` when none are given.
3. Prints the copy's path.

Base method (verbatim, four-space class indent):

```python
    def _send_request(self, body):
        conn = self._upstream_conn
        conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
        for name, value in self._upstream_headers():
            conn.putheader(name, value)
        conn.endheaders(body or None)
        return conn.getresponse()
```

Patched method (the lever, with no safety paths, D2):

```python
    def _send_request(self, body):
        conn = self._upstream_conn
        conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
        headers = self._upstream_headers()
        names = {name.lower() for name, _ in headers}
        hot = self.command == "POST" and urlsplit(self.path).path == "/v1/messages"
        if hot and "content-encoding" not in names and len(body) >= 4096:
            body = gzip.compress(body, compresslevel=6)
            headers = [(n, v) for n, v in headers if n.lower() != "content-length"]
            headers += [("Content-Encoding", "gzip"), ("Content-Length", str(len(body)))]
        if hot:
            headers += [(n, v) for n, v in I438_EXTRA if n.lower() not in names]
        for name, value in headers:
            conn.putheader(name, value)
        conn.endheaders(body or None)
        return conn.getresponse()
```

Run (timeout 60 s): `python3 -I <S>/i438/proto/make.py "$PWD" <S>/i438/proto/G`. Unless the marker reads `none`, also run `python3 -I <S>/i438/proto/make.py "$PWD" <S>/i438/proto/E2 <each name=value from the Missing first-party headers line>`. For each copy, the load check (timeout 30 s) must print a path under that copy: `env -i PYTHONPATH=<copy>/python "$(sed -n 's/^interp //p' <S>/i438/rig/conditions.txt)" -s -P -c 'import agent_tools.cache_proxy as m; print(m.__file__, m.I438_EXTRA)'`.

- [ ] **Step 4: Screen each candidate in order**

`reduce.py check` writes `candidate` (the session's row map), `diff`, `removed` (AC1 diff rows gone), `added` (new diff rows) and `body_json_ok`. The encoding rows are `body-encoding`, `header:content-encoding`, `header:content-length` and `header-order`.

| X | Proxy | `--proxied-env` and wire-check session variables | Wire check (D10, spec § AC1 capture) |
|---|-------|------------------------------------|------------|
| R0 | stock | none | none: AC1's proxied capture is R0's |
| E3 | stock | `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1` | `candidate` `beta-tokens` has a token starting `fine-grained-tool-streaming`, or a `tools:<name>:keys` row contains `eager_input_streaming`, where AC1's `proxied` map had neither |
| G | prototype G | none | `header:content-encoding` is `gzip`, `raw_body_bytes` < `body_bytes` in `body-encoding`, and `body_json_ok` |
| E1 | stock | `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` | `added` is empty and `removed` is not, encoding rows aside. If AC1's `rows` minus the encoding rows is empty, the check is recorded as `vacuous` and the timed run proceeds |
| C | prototype G | `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` | both E1's and G's checks |
| E2 | prototype E2 | none | every `name=value` from the marker appears once in `candidate` as `header:<name>` with that value, and G's check holds |

For each X in the order of § Invariants, after the cutoff check:

1. **Wire check** (every X except R0). Start mitmdump with `run_in_background: true`: `cd <S>/i438/mitm && launch-scope exec … -- devenv -O packages:pkgs "mitmproxy" shell -- mitmdump -q --mode reverse:https://api.anthropic.com --listen-host 127.0.0.1 --listen-port 27392 --set confdir=<S>/i438/mitm/conf -s <S>/i438/mitm/addon.py --set i438_out=<S>/i438/mitm/records/<X>`. Await it (timeout 60 s): `curl -q --noproxy '*' -s -o /dev/null --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27392/`. Start X's proxy with `run_in_background: true` and `--upstream http://127.0.0.1:27392`: stock is `sh <S>/i438/rig/run-proxy.sh <S>/i438/runs/<X>-wire.log <S>/i438/runs/proxy.pid --upstream http://127.0.0.1:27392`, and a prototype is `sh <S>/i438/rig/run-prototype.sh <S>/i438/runs/<X>-wire.log <S>/i438/runs/proxy.pid <S>/i438/proto/<G|E2>/python --upstream http://127.0.0.1:27392`. Await health (timeout 60 s): `curl -q --noproxy '*' -fsS --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27391/_proxy/health` prints `{"service":"cache-proxy","status":"ok"}`. Run one session (timeout 300 s): `launch-scope exec … -- <S>/i438/rig/session.sh <S>/i438/runs/<X>-wire.jsonl CLAUDE_ACCOUNT="$ACCOUNT" <X's variables>`. When `ac1-rows.json` has `"fallback": true`, the session also sets `ANTHROPIC_LOG=debug` with `2> <S>/i438/runs/<X>-wire.stderr`, and `check` below gets `--sdk-log <S>/i438/runs/<X>-wire.stderr` (D16). Stop the proxy (`kill "$(cat <S>/i438/runs/proxy.pid)"`) and mitmdump (`kill "$(lsof -nP -t -iTCP:27392 -sTCP:LISTEN)"`). Then run `cd <S>/i438/mitm && python3 -I reduce.py check --against ac1-rows.json --proxied records/<X> --out-json <S>/i438/runs/<X>-wire.json` and judge the row's check from that JSON. If the check fails, fix the rig once (for example, the prototype did not load), rename `<X>-wire.json` to `<X>-wire.attempt-1.json`, delete `<S>/i438/mitm/records/<X>` and any `<X>-wire.stderr`, and capture again, so the recapture's directory holds exactly one main request. If it fails a second time, write `<S>/i438/runs/<X>.wire-failed` with the failing fields, and go to the next X without timing.
2. **Timed run.** Start X's proxy with `run_in_background: true` and its default upstream (no `--upstream`), logging to `<S>/i438/runs/<X>.log`, and await health. Run (timeout 3600 s; about 5 minutes is typical): `launch-scope exec … -- python3 -I <S>/i438/rig/ttft.py --rig <S>/i438/rig --proxy-log <S>/i438/runs/<X>.log --out <S>/i438/runs/<X>.json <one --proxied-env per variable of X>`. Stop the proxy. If `valid` is false, rename the output to `<X>.invalid-1.json` and rerun once with a fresh log. That second output is `<X>.json` whatever it shows.
3. Delete `<S>/i438/mitm/records/<X>` and any `<S>/i438/runs/<X>-wire.stderr`. After the last candidate, also delete `<S>/i438/mitm/conf`, the mitmproxy CA.

- [ ] **Step 5: Record**

Append `## Screens` to the report, containing these parts in order:

1. A conditions line: the date, `git rev-parse --short HEAD`, "rig as in § Conditions", the account, `deadline_at`, and the harness command shape with `--proxied-env` per candidate.
2. The table `| Candidate | Lever | Wire check | Valid | Median proxied ms | Median direct ms | Δ ms | Passes | Quartiles proxied | Quartiles direct | Median within-pair ms |`, with one row per candidate in rank order (R0 first). The wire check is `holds`, `vacuous`, `failed` or `—`. A candidate that was not timed shows `not run: <wire check failed|attempt deadline cutoff|a candidate ranked before it passed|E2 dropped out (no missing first-party header)>` in place of its numbers.
3. One line per timed candidate: `<X> counted TTFT ms — proxied: [..]; direct: [..]`, in run order, then `<X> proxy ttfb_ms: [..]; upstream_conn: [..]`.
4. For each wire check that held, one line naming the rows it removed or added (from `<X>-wire.json`).
5. If R0 passed, the sentence: "R0 passed its screen, so these screens could not separate the levers from noise (D4)."
6. The line `Screen winner: <X>`. X is the first candidate in rank order E3, G, E1, C, E2 whose `<X>.json` has `"passes": true`, or `none`. R0 never wins.

- [ ] **Step 6: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; R=<S>/i438/runs
test "$(grep -Ec '^Screen winner: (E3|G|E1|C|E2|none)$' "$f")" -eq 1
winner=$(sed -n 's/^Screen winner: //p' "$f")
expect=$(python3 -I - "$R" <<'EOF'
import json, sys
from pathlib import Path
runs = Path(sys.argv[1])
for x in ("E3", "G", "E1", "C", "E2"):
    out = runs / f"{x}.json"
    if out.exists() and json.loads(out.read_text())["passes"]:
        print(x); break
else:
    print("none")
EOF
)
test "$winner" = "$expect"
test -s "$R/R0.json" || test -e "$R/R0.skipped"
for x in E3 E1; do test -s "$R/$x.json" || test -e "$R/$x.wire-failed" || test -e "$R/$x.skipped"; done
if grep -nE 'sk-ant-|Bearer |oat01' "$f"; then exit 1; fi
if grep -nF "$HOME" "$f"; then exit 1; fi
for p in 27391 27392; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done
echo screens-recorded
```

Expected: `screens-recorded`. At the starting commit the first `grep` fails, because there is no winner line.

- [ ] **Step 7: Commit**

```bash
git add docs/spikes/cache-proxy-ttft-gap.md
git commit -m "docs(issue-438): lever screens and the screen winner"
```

Report DONE with the winner and each candidate's Δ. A failing Δ is reported as observed and never re-measured.
