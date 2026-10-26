# Task 5: Timed run and routing verdict (AC3)

This task covers spec § Timed run and the second half of § Evidence, per D6, D8, D9, D12, D13 and D14. On mbp, at the M that Task 4 recorded, it rebuilds the rig. It then runs one warm-up pair and 100 valid alternating pairs of fresh `claude -p` launches through M's wrapper, applies the decision rule that Task 4 committed in § Method, and writes the verdict line that Task 6 branches on. § Resume continues a run that a usage limit stopped. § Re-measurement is this task's half of a new measurement, after Task 4's § Re-measurement.

**Files:**
- Modify: `docs/spikes/cache-proxy-ttft-gap.md` (append `### Timed run (AC3)` and `### Routing verdict`; insert one pointer paragraph under the title)
- Create: `docs/spikes/cache-proxy-ttft-gap-450-runs.md`
- Modify: `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` (row AC3)

**Interfaces:**
- Consumes these report whole lines, which Task 4 wrote: `Issue 450 measured head: <40-hex>` (M) and `Issue 450 probe term: <p> ms` (p). Also § Method, the acceptance record, and `./result` from `just build mbp` of M.
- Produces, for Task 6 (D14), each exactly once in the report:
  - `Issue 450 timed run: estimate <e> ms, 95% CI [<lo>, <hi>] ms, <within|outside> the +100 ms bound`, or `Issue 450 timed run: no valid measurement`;
  - `Issue 450 routing default: <on|opt-in>`, which is `on` exactly when the timed-run line says `within`.
  - In the sibling, the whole line `Timed run head: <40-hex>`, which equals M.

**Invariants:**
- The rule is § Method's, applied as written: d = (routed `ttft_ms` + p) − direct `ttft_ms`; the median, with a 10,000-resample percentile bootstrap at seed 450; within when the upper end is ≤ +100 ms. The run is never extended or repeated to move the CI. A pair is replaced only for D8's reasons, and an invalid run is rerun once (D8).
- Every run goes through a copy of M's built mod. Routed leaves `CLAUDE_CACHE_PROXY` unset and direct sets `0`; nothing else differs (D6).
- The experiment proxy runs only in Steps 4–6, is stopped by pid before this task reports, and nothing listens on 27450 at the end. Port 27183 is only listed.
- #438's text stays byte-identical, with the pointer paragraph as its only addition (D9).
- Nothing under `<S>` or in `$(git rev-parse --git-dir)` is committed.

## Rig files

Step 2 writes these files into `<S>/i450/rig/` with exactly this content. Each was run during planning against a stand-in claude, a local `ProxyServer` and the current build. `mkrig450.sh`, `run-proxy450.sh` and `verbatim450.py` are the same files that Task 4 writes.

### `mkrig450.sh`

Builds the rig from `./result` (D12). The experiment proxy is the built plist's service command with only the port swapped. `before` is the launcher text at `51e2b7c9` under M's substitutions and shebang (D5).

```bash
#!/usr/bin/env bash
# mkrig450.sh <worktree> <rig dir>: the issue-450 rig from <worktree>/result (D5-D7, D12).
# Writes <rig>/conditions.env, the mod copies mod-27450 and mod-27451, and the AC2 `before` copy.
set -euo pipefail
wt=$1 rig=$2
closure=$(nix-store -qR "$wt/result")
one() {
  local hits
  hits=$(printf '%s\n' "$closure" | grep -E -- "$1" || true)
  if [ "$(printf '%s\n' "$hits" | grep -c .)" -ne 1 ]; then
    echo "mkrig450: want one store path matching $1, got: ${hits:-none}" >&2
    exit 1
  fi
  printf '%s\n' "$hits"
}
mod=$(one '-claude-accounts-mod$')
plist=$(one '-org\.nix-community\.home\.claude-cache-proxy\.plist$')
service=$(plutil -extract ProgramArguments.2 raw -o - "$plist")
launcher=$(printf '%s\n' "$service" |
  sed -nE 's|^/bin/wait4path /nix/store && exec (/nix/store/[^ ]+-agent-tools-cache-proxy) --port 27183 --keepalive$|\1|p')
[ -n "$launcher" ] || { echo "mkrig450: unexpected service command: $service" >&2; exit 1; }
ca=$(plutil -extract EnvironmentVariables.SSL_CERT_FILE raw -o - "$plist")
interp=$(sed -nE 's|^exec (/nix/store/[^ ]+/bin/python3) -I -m agent_tools\.cache_proxy "\$@"$|\1|p' "$launcher")
[ -n "$interp" ] || { echo "mkrig450: no interpreter in $launcher" >&2; exit 1; }
value() { sed -n "s|^$1=||p" "$mod/bin/claude-account"; }
claude_bin=$(value DEFAULT_CLAUDE_BIN)
version=$("$claude_bin" --version | sed -n 's/^\([0-9][0-9.]*\) (Claude Code)$/\1/p')
[ -n "$version" ] || { echo "mkrig450: no version from $claude_bin" >&2; exit 1; }
grep -qx 'CACHE_PROXY_URL=http://127.0.0.1:27183' "$mod/bin/claude-account"
mkdir -p "$rig/runs" "$rig/cwd" "$rig/bench"
copy() { # <dest> <claude-account text>: M's built mod with that launcher text
  rm -rf "$1"
  cp -R "$mod" "$1"
  chmod -R u+w "$1"
  cp "$2" "$1/bin/claude-account"
  chmod 755 "$1/bin/claude-account"
}
for port in 27450 27451; do
  sed "s|^CACHE_PROXY_URL=http://127.0.0.1:27183\$|CACHE_PROXY_URL=http://127.0.0.1:$port|" \
    "$mod/bin/claude-account" > "$rig/claude-account.$port"
  copy "$rig/mod-$port" "$rig/claude-account.$port"
done
# before (D5): the launcher text at 51e2b7c9 under M's five substitutions and M's shebang.
{
  head -n 1 "$mod/bin/claude-account"
  git -C "$wt" show 51e2b7c9:home/common/claude-code/accounts/bin/claude-account | tail -n +2 |
    sed -e "s|^JQ=jq\$|JQ=$(value JQ)|" -e "s|^GIT=git\$|GIT=$(value GIT)|" \
      -e "s|^CURL=curl\$|CURL=$(value CURL)|" -e "s|^DEFAULT_CLAUDE_BIN=\$|DEFAULT_CLAUDE_BIN=$claude_bin|" \
      -e "s|^CACHE_PROXY_URL=\$|CACHE_PROXY_URL=http://127.0.0.1:27450|"
} > "$rig/claude-account.before"
for key in JQ GIT CURL DEFAULT_CLAUDE_BIN; do grep -q "^$key=/nix/store/" "$rig/claude-account.before"; done
copy "$rig/before" "$rig/claude-account.before"
for dir in mod-27450 mod-27451 before; do "$rig/$dir/bin/claude-account" help > /dev/null; done
cat > "$rig/conditions.env" <<CONDITIONS
MOD=$mod
PLIST=$plist
LAUNCHER=$launcher
CA=$ca
INTERP=$interp
CLAUDE_BIN_PATH=$claude_bin
V=$version
CONDITIONS
echo "mkrig450: V=$version"
```

### `run-proxy450.sh`

Starts the experiment proxy (`proxy`) or the wire-check runner (`wire`), and records its pid.

```sh
#!/bin/sh
# run-proxy450.sh <dir> <proxy|wire> <port> <log>: runs in the foreground, from <dir>/conditions.env,
# M's cache-proxy launcher with the service's arguments but the port (D6), or the wire-check runner
# beside this script on M's interpreter (D7). Its pid goes to <dir>/<mode>-<port>.pid.
set -eu
dir=$1 mode=$2 port=$3 log=$4
. "$dir/conditions.env"
echo $$ > "$dir/$mode-$port.pid"
case "$mode" in
  proxy) exec env SSL_CERT_FILE="$CA" "$LAUNCHER" --port "$port" --keepalive 2>>"$log" ;;
  wire) exec env SSL_CERT_FILE="$CA" "$INTERP" -I "$(dirname "$0")/wire450.py" --port "$port" 2>>"$log" ;;
  *) echo "run-proxy450: mode must be proxy or wire" >&2; exit 2 ;;
esac
```

### `ttft450.py`

The AC3 harness (D6, D8, D13). Exit 0 is complete, 3 `rig_invalid`, 4 `run_invalid` and 5 `usage_limit`.

```python
"""AC3 timed run (issue 450 D6, D8): fresh `claude -p` launches through a mod copy, routed and direct.

python3 -I ttft450.py --mod DIR --proxy-log FILE --cwd DIR --head SHA --out FILE [--resume] [--routed-switch 1]
Routed leaves CLAUDE_CACHE_PROXY unset (or sets 1 with --routed-switch 1), direct sets it to 0;
nothing else differs. One JSON object per line goes to --out: a header, each run, each pair's
verdict and a terminal record. Nothing credential-shaped is read or written. Exit 0 complete,
3 rig_invalid, 4 run_invalid, 5 usage_limit.
"""
import argparse, json, os, re, signal, subprocess, sys, threading, time
from datetime import datetime
from urllib.parse import urlsplit

PAIRS = 100
MAX_INVALID = 10
WARMUP_ATTEMPTS = 3
ACCOUNT = "p1"
PROMPT = "Reply with exactly: ok"
CLAUDE_ARGS = ["-p", "--model", "haiku", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", PROMPT]
# AGENT_LAUNCH_SCOPE stays, so launch-scope can still reap a client that left the session (R450-01).
KEEP = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TMPDIR", "SHELL", "TERM",
        "AGENT_LAUNCH_SCOPE")
INSTRUMENT = {"CLAUDE_CODE_EMIT_STARTUP_TIMING": "1"}
FIRST_BLOCKS = {"thinking": "thinking", "redacted_thinking": "thinking", "text": "text"}
LIMIT_TEXT = re.compile(r"usage limit|rate limit|hit your limit|limit reached|out of extra usage", re.I)
RUN_SECONDS = 150


def epoch_ms(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000


def proxy_requests(log_path, start_ms, end_ms):
    """ttfb_ms of each POST /v1/messages the proxy began handling inside [start_ms, end_ms]."""
    found = []
    with open(log_path) as log:
        for line in log:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (event.get("event") != "request" or event.get("method") != "POST"
                    or urlsplit(event.get("path", "")).path != "/v1/messages"):
                continue
            began = epoch_ms(event["ts"]) - event.get("duration_ms", 0)
            if start_ms <= began <= end_ms:
                found.append(event.get("ttfb_ms"))
    return found


def error_kind(code, result):
    if result is None:
        return "no_result"
    if not result.get("is_error"):
        return None if code == 0 else "exit"
    text = result.get("result") if isinstance(result.get("result"), str) else ""
    if result.get("api_error_status") == 429 or LIMIT_TEXT.search(text):
        return "usage_limit"
    return "error"


def run_once(args, arm):
    env = {key: os.environ[key] for key in KEEP if key in os.environ}
    env.update(CLAUDE_ACCOUNT=ACCOUNT, **INSTRUMENT)
    if arm == "direct":
        env["CLAUDE_CACHE_PROXY"] = "0"
    elif args.routed_switch == "1":
        env["CLAUDE_CACHE_PROXY"] = "1"
    argv = [os.path.join(args.mod, "bin", "claude-account"), "run", *CLAUDE_ARGS]
    launched = time.time() * 1000
    process = subprocess.Popen(argv, cwd=args.cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    record = {"kind": "run", "arm": arm, "t_launch": round(launched, 1), "first_block": None,
              "wall_ttft_ms": None}
    result = None
    expired = threading.Event()

    def expire():
        # A silent client never yields a line, so the deadline is a timer, not a check in the loop (R450-05).
        expired.set()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass

    timer = threading.Timer(RUN_SECONDS, expire)
    timer.daemon = True
    timer.start()
    try:
        for line in process.stdout:
            now = time.time() * 1000
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "stream_event":
                inner = event.get("event", {})
                if inner.get("type") == "content_block_start" and "block_type" not in record:
                    record["block_type"] = inner.get("content_block", {}).get("type")
                    record["first_block"] = FIRST_BLOCKS.get(record["block_type"])
                if inner.get("type") == "content_block_delta" and record["wall_ttft_ms"] is None:
                    record["wall_ttft_ms"] = round(now - launched, 1)
            if event.get("type") == "result":
                result = event
    finally:
        timer.cancel()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        record["exit"] = process.wait()
    record["t_exit_ms"] = round(time.time() * 1000 - launched, 1)
    record["ttft_ms"] = result.get("ttft_ms") if result else None
    record["time_to_request_ms"] = result.get("time_to_request_ms") if result else None
    record["timed_out"] = expired.is_set()
    record["error_kind"] = "timeout" if record["timed_out"] else error_kind(record["exit"], result)
    if record["error_kind"] is not None and result is not None:
        record["api_error_status"] = result.get("api_error_status")
        record["error_excerpt"] = str(result.get("result", ""))[:300]
    ttfbs = proxy_requests(args.proxy_log, launched, launched + record["t_exit_ms"])
    record["proxy_lines"], record["proxy_ttfb_ms"] = len(ttfbs), ttfbs
    return record


def pair_reasons(runs):
    reasons = []
    for run in runs:
        arm = run["arm"]
        if run["exit"] != 0 or run["error_kind"] is not None:
            reasons.append(f"{arm}: exit {run['exit']}, error {run['error_kind']}")
        if not isinstance(run["ttft_ms"], (int, float)):
            reasons.append(f"{arm}: no ttft_ms")
        if run["first_block"] is None:
            reasons.append(f"{arm}: first block {run.get('block_type')}")
        expected = 1 if arm == "routed" else 0
        if run["proxy_lines"] != expected:
            reasons.append(f"{arm}: {run['proxy_lines']} proxy lines, expected {expected}")
    return reasons


def main():
    parser = argparse.ArgumentParser()
    for name in ("--mod", "--proxy-log", "--cwd", "--head", "--out"):
        parser.add_argument(name, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--routed-switch", choices=("unset", "1"), default="unset")
    args = parser.parse_args()
    # SIGTERM (a reap or a host stop) raises SystemExit, so run_once's finally kills the client's group (R450-01).
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    mod_text = open(os.path.join(args.mod, "bin", "claude-account")).read()
    records = []
    if os.path.exists(args.out):
        if not args.resume:
            sys.exit(f"{args.out} exists; pass --resume to continue it")
        with open(args.out) as handle:
            records = [json.loads(line) for line in handle]
        header = records[0]
        if (header.get("head"), header.get("routed_switch"), header.get("mod_text")) != (
                args.head, args.routed_switch, mod_text):
            sys.exit("resume refused: the head, the routed switch or the mod differs from the header's")
        if records[-1]["kind"] != "usage_limit":
            sys.exit(f"resume refused: the run ended with {records[-1]['kind']}")
    elif args.resume:
        sys.exit(f"{args.out} does not exist; nothing to resume")
    pairs = [r for r in records if r["kind"] == "pair"]
    valid = sum(1 for r in pairs if r["valid"])
    invalid = sum(1 for r in pairs if not r["valid"])
    index = max((r["pair"] for r in records if r["kind"] == "run" and isinstance(r["pair"], int)),
                default=-1) + 1
    with open(args.out, "a") as out:
        def write(record):
            out.write(json.dumps(record) + "\n")
            out.flush()

        def stop(kind, code):
            write({"kind": kind, "ts": time.time() * 1000, "valid_pairs": valid, "invalid_pairs": invalid})
            print(json.dumps({"stopped": kind, "valid_pairs": valid, "invalid_pairs": invalid}))
            return code

        if records:
            write({"kind": "resume", "ts": time.time() * 1000})
        else:
            write({"kind": "header", "head": args.head, "mod": args.mod, "pairs": PAIRS,
                   "max_invalid": MAX_INVALID, "account": ACCOUNT, "routed_switch": args.routed_switch,
                   "mod_text": mod_text})

        def run_pair(label, order):
            runs = []
            for position, arm in enumerate(order):
                run = run_once(args, arm)
                run.update(pair=label, position=position)
                write(run)
                runs.append(run)
                if run["error_kind"] == "usage_limit":
                    return runs, None
            return runs, pair_reasons(runs)

        for attempt in range(WARMUP_ATTEMPTS):
            runs, reasons = run_pair("warmup", ("routed", "direct"))
            if reasons is None:
                return stop("usage_limit", 5)
            write({"kind": "warmup", "attempt": attempt, "valid": not reasons, "reasons": reasons})
            if not reasons:
                break
        else:
            return stop("rig_invalid", 3)
        while valid < PAIRS:
            order = ("routed", "direct") if index % 2 == 0 else ("direct", "routed")
            runs, reasons = run_pair(index, order)
            if reasons is None:
                return stop("usage_limit", 5)
            write({"kind": "pair", "pair": index, "valid": not reasons, "reasons": reasons})
            if reasons:
                invalid += 1
                if invalid > MAX_INVALID:
                    return stop("run_invalid", 4)
            else:
                valid += 1
            index += 1
            print(f"pair {index - 1}: {'valid' if not reasons else 'INVALID ' + '; '.join(reasons)} "
                  f"({valid}/{PAIRS} valid, {invalid} invalid)", flush=True)
        return stop("complete", 0)


if __name__ == "__main__":
    sys.exit(main())
```

### `analyze450.py`

The AC3 decision rule and diagnostics (D8), and the per-run rows.

```python
"""AC3 decision rule (issue 450 D8): python3 -I analyze450.py --runs FILE --probe-ms P --out FILE --rows-md FILE
(or --runs FILE --rows-md FILE --rows-only, which writes the per-run rows of any run, complete or not).

Fixed before any number exists. d = (routed ttft_ms + p) - direct ttft_ms per valid counted pair;
the estimate is the median of d, its 95% CI a percentile bootstrap over pairs (10,000 resamples,
seed 450); within the bound when the CI's upper end is <= +100 ms. Diagnostics never decide.
"""
import argparse, json, random, statistics, sys

SEED = 450
RESAMPLES = 10_000
BOUND_MS = 100.0
PAIRS = 100


def bootstrap_ci(values):
    rng = random.Random(SEED)
    medians = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(RESAMPLES))
    return medians[int(RESAMPLES * 0.025)], medians[int(RESAMPLES * 0.975) - 1]


def quartiles(values):
    q1, q2, q3 = statistics.quantiles(values, n=4)
    return [round(q1, 1), round(q2, 1), round(q3, 1)]


def thinking(runs):
    first = [r for r in runs if r["first_block"] == "thinking"]
    text = [r for r in runs if r["first_block"] == "text"]
    delay = (round(statistics.median(r["ttft_ms"] for r in first) - statistics.median(r["ttft_ms"] for r in text), 1)
             if first and text else None)
    return {"thinking_first": len(first), "rate": round(len(first) / len(runs), 3), "delay_ms": delay}


def write_rows(records, path):
    verdict = {r["pair"]: r["valid"] for r in records if r["kind"] == "pair"}
    with open(path, "w") as rows:
        rows.write("| pair | position | arm | ttft_ms | time_to_request_ms | wall_ttft_ms | first block "
                   "| exit | error | proxy lines | proxy ttfb_ms | pair valid |\n"
                   "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in records:
            if r["kind"] != "run":
                continue
            ttfb = ", ".join(str(t) for t in r["proxy_ttfb_ms"]) or "—"
            state = "warm-up" if r["pair"] == "warmup" else verdict.get(r["pair"], "unfinished")
            rows.write(f"| {r['pair']} | {r['position']} | {r['arm']} | {r['ttft_ms']} | {r['time_to_request_ms']} "
                       f"| {r['wall_ttft_ms']} | {r.get('block_type')} | {r['exit']} | {r['error_kind'] or '—'} "
                       f"| {r['proxy_lines']} | {ttfb} | {state} |\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", required=True)
    parser.add_argument("--probe-ms", type=float)
    parser.add_argument("--out")
    parser.add_argument("--rows-md", required=True)
    parser.add_argument("--rows-only", action="store_true")
    args = parser.parse_args()
    records = [json.loads(line) for line in open(args.runs)]
    if args.rows_only:
        write_rows(records, args.rows_md)
        return
    if args.probe_ms is None or args.out is None:
        sys.exit("--probe-ms and --out are required unless --rows-only")
    runs = {}
    for r in records:
        if r["kind"] == "run" and isinstance(r["pair"], int):
            runs.setdefault(r["pair"], {})[r["arm"]] = r
    verdicts = [r for r in records if r["kind"] == "pair"]
    valid = [runs[v["pair"]] for v in verdicts if v["valid"]]
    if len(valid) != PAIRS or records[-1]["kind"] != "complete":
        sys.exit(f"not a complete run: {len(valid)} valid pairs, last record {records[-1]['kind']}")
    p = args.probe_ms
    d = [(pair["routed"]["ttft_ms"] + p) - pair["direct"]["ttft_ms"] for pair in valid]
    low, high = bootstrap_ci(d)
    startup = [(pair["routed"]["wall_ttft_ms"] - pair["routed"]["ttft_ms"])
               - (pair["direct"]["wall_ttft_ms"] - pair["direct"]["ttft_ms"]) for pair in valid]
    s_low, s_high = bootstrap_ci(startup)
    arms = {arm: [pair[arm] for pair in valid] for arm in ("routed", "direct")}
    ttfb = [t for pair in valid for t in pair["routed"]["proxy_ttfb_ms"]]
    summary = {
        "pairs": len(valid), "invalid_pairs": sum(1 for v in verdicts if not v["valid"]),
        "probe_ms": p, "seed": SEED, "resamples": RESAMPLES,
        "estimate_ms": round(statistics.median(d), 2), "ci_ms": [round(low, 2), round(high, 2)],
        "within_bound": high <= BOUND_MS,
        "diagnostics": {
            "ttft_quartiles_ms": {arm: quartiles([r["ttft_ms"] for r in rs]) for arm, rs in arms.items()},
            "mean_d_ms": round(statistics.mean(d), 1),
            "thinking": {arm: thinking(rs) for arm, rs in arms.items()},
            "paired_median_wall_ttft_ms": round(statistics.median(
                pair["routed"]["wall_ttft_ms"] - pair["direct"]["wall_ttft_ms"] for pair in valid), 1),
            "paired_median_startup_ms": round(statistics.median(startup), 1),
            "startup_ci_ms": [round(s_low, 1), round(s_high, 1)],
            "proxy_ttfb_quartiles_ms": quartiles(ttfb),
        },
    }
    with open(args.out, "w") as handle:
        json.dump(summary, handle, indent=2)
    write_rows(records, args.rows_md)
    print(json.dumps({k: summary[k] for k in ("pairs", "invalid_pairs", "estimate_ms", "ci_ms", "within_bound")}))


if __name__ == "__main__":
    main()
```

### `verbatim450.py`

The gate that #438's text is untouched (D9).

```python
"""#438's text stays verbatim (D9): python3 -I verbatim450.py <report> [--pointer]

Everything before `## Issue 450`, less the pointer paragraph under the title, must equal the
report at 51e2b7c9; --pointer also requires that paragraph. Run from the repository root."""
import subprocess
import sys

path = sys.argv[1]
base = subprocess.run(["git", "show", "51e2b7c9:" + path], capture_output=True, text=True, check=True).stdout
head, found, _ = open(path).read().partition("\n## Issue 450\n")
if not found:
    sys.exit("no ## Issue 450 section")
lines = head.split("\n")
pointer = len(lines) > 3 and lines[2].startswith("§ Issue 450") and lines[3] == ""
if pointer:
    lines = lines[:2] + lines[4:]
if "\n".join(lines) != base:
    sys.exit("#438's text changed")
if "--pointer" in sys.argv[2:] and not pointer:
    sys.exit("no pointer line under the title")
print("438-text-verbatim")
```

## Steps

`<S>/i450` holds the rig outputs and `<S>/i450/runs` the raw results. `A=.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` is the acceptance record, and `f=docs/spikes/cache-proxy-ttft-gap.md` the report.

- [ ] **Step 0: Preconditions**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md
M=$(sed -n 's/^Issue 450 measured head: //p' "$f"); test "$(printf '%s\n' "$M" | grep -c .)" -eq 1
test "$(grep -Ecx 'Issue 450 probe term: -?[0-9]+(\.[0-9]+)? ms' "$f")" -eq 1
grep -qxF '### Method' "$f"
if grep -Eq '^Issue 450 (timed run|routing default):' "$f"; then echo 'timed already: use § Resume or § Re-measurement'; exit 1; fi
surface=(home/common/claude-code/accounts home/common/claude-code/default.nix python/agent_tools/cache_proxy.py)
if git diff -U0 "$M" HEAD -- "${surface[@]}" | grep -E '^[-+]' | grep -Ev '^(\+\+\+|---) ' | grep -Ev '^[-+][[:space:]]*(#.*)?$'; then echo 'measured surface changed since M: Task 4 § Re-measurement'; exit 1; fi
n() { git show "$1:flake.lock" | jq -c '.nodes["claude-code"].locked'; }; test "$(n "$M")" = "$(n HEAD)"
printf '%s\n' "$M"
```

Any failure is BLOCKED, with the output. Keep the printed M.

- [ ] **Step 1: Build**

Run (timeout 3600 s): `launch-scope exec … -- just build mbp`. Step 0 allows only comment lines to differ from M in the measured surface, so the rebuilt outputs behave as M's.

- [ ] **Step 2: Rig**

Write § Rig files into `<S>/i450/rig/`, then run (timeout 300 s) `bash <S>/i450/rig/mkrig450.sh "$PWD" <S>/i450` and `printf '%s\n' "$M" > <S>/i450/M`. Expected: `mkrig450: V=<V>`, where V is the version that § Measurement conditions records; a different V is BLOCKED.

- [ ] **Step 3: Ports and the service**

Run (timeout 30 s): `if lsof -nP -iTCP:27450 -sTCP:LISTEN; then exit 1; fi; lsof -nP -t -iTCP:27183 -sTCP:LISTEN > <S>/i450/service-pid.before || true`. A busy port is BLOCKED. An empty service pid is recorded as `none`.

- [ ] **Step 4: Experiment proxy**

Start it with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh <S>/i450/rig/run-proxy450.sh <S>/i450 proxy 27450 <S>/i450/runs/proxy-27450.log`. Await it (timeout 60 s): `curl -q --noproxy '*' -fsS -o /dev/null --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27450/_proxy/health`.

- [ ] **Step 5: Timed run (AC3)**

Run (timeout 3600 s; 15–20 min is typical):

```bash
status=0
launch-scope exec … -- python3 -I <S>/i450/rig/ttft450.py --mod <S>/i450/mod-27450 --proxy-log <S>/i450/runs/proxy-27450.log --cwd <S>/i450/cwd --head "$(cat <S>/i450/M)" --out <S>/i450/runs/runs.jsonl > <S>/i450/runs/harness.out 2>&1 || status=$?
tail -n 2 <S>/i450/runs/harness.out; echo "harness exit $status"
```

With `H="$(git rev-parse --git-dir)/issue-450-suspended"`, on any exit but 0, first copy the active runs file and, when it exists, the invalid first run to the handoff (D13; R450-02): `mkdir -p "$H"; cp <S>/i450/runs/runs.jsonl "$H/"; if test -f <S>/i450/runs/runs.invalid-1.jsonl; then cp <S>/i450/runs/runs.invalid-1.jsonl "$H/"; fi`. A `runs.invalid-1.jsonl` in `<S>/i450/runs` or `$H` is the durable record that D8's one rerun is consumed. Then:
- 0: Step 6.
- 5 (`usage_limit`): Step 6, then BLOCKED with `blocked_on=usage_limit`, the valid-pair count and the handoff path; § Resume continues the run.
- 4 (`run_invalid`): when `<S>/i450/runs/runs.invalid-1.jsonl` does not exist, this was the first run: `mv <S>/i450/runs/runs.jsonl <S>/i450/runs/runs.invalid-1.jsonl`, `rm -f "$H/runs.jsonl"`, `cp <S>/i450/runs/runs.invalid-1.jsonl "$H/"`, and run this step once more without `--resume` (a fresh rerun with a new header). When it exists, the rerun was invalid too and there is no valid measurement (D8): Step 6, then Step 8's no-valid branch.
- 3 (`rig_invalid`): Step 6, then BLOCKED `timed run: warm-up invalid three times` with `jq -c 'select(.kind == "warmup") | .reasons' <S>/i450/runs/runs.jsonl`. No counted pair ran, so it is not an invalid run (D13).
- Anything else: Step 6, then BLOCKED with the tail of `harness.out`.

- [ ] **Step 6: Stop and check**

Run (timeout 30 s): `kill "$(cat <S>/i450/proxy-27450.pid)"`, then one `sleep 2`, then `if lsof -nP -iTCP:27450 -sTCP:LISTEN; then exit 1; fi; lsof -nP -t -iTCP:27183 -sTCP:LISTEN > <S>/i450/service-pid.after || true; cmp <S>/i450/service-pid.before <S>/i450/service-pid.after && echo service-unchanged`. A port still listening is BLOCKED. A changed service PID is recorded with both values in § Timed run (AC3) and reported as DONE_WITH_CONCERNS: this task never contacts 27183. After a stop (Step 5 created `$H`), also append the line `before <pid> after <pid>` to `$H/service-pids`.

- [ ] **Step 7: Analysis**

`P=$(sed -n 's/^Issue 450 probe term: \(.*\) ms$/\1/p' docs/spikes/cache-proxy-ttft-gap.md)`. Run (timeout 120 s): `python3 -I <S>/i450/rig/analyze450.py --runs <S>/i450/runs/runs.jsonl --probe-ms "$P" --out <S>/i450/runs/summary.json --rows-md <S>/i450/runs/rows.md`. It prints `{"pairs", "invalid_pairs", "estimate_ms", "ci_ms", "within_bound"}`; a refusal is BLOCKED. Write the rows of an invalid first run with `--runs <S>/i450/runs/runs.invalid-1.jsonl --rows-md <S>/i450/runs/rows.invalid-1.md --rows-only`. In the no-valid branch, do only `--rows-only`, for both runs.

- [ ] **Step 8: Record the timed run and the verdict**

1. Create `docs/spikes/cache-proxy-ttft-gap-450-runs.md`. It holds the title `# Cache proxy TTFT gap — issue 450 timed-run rows`, then the whole line `Timed run head: «fill: M»`, then: `Every run of the timed run in [the report](cache-proxy-ttft-gap.md) § Issue 450, measured at «fill: M, short», in run order: warm-ups, counted pairs whether valid or not, and any pair a stop cut short (`unfinished`). `ttft_ms` and `time_to_request_ms` are the client's own; `wall_ttft_ms` is the harness's time from launch to the first `content_block_delta`.` Then `rows.md`. With an invalid first run, the rows go under `## First run (invalid, rerun once per D8)` (from `rows.invalid-1.md`) and `## Counted run` (from `rows.md`).
2. Append to the report, after one blank line, filling from `summary.json`, `harness.out` and the runs file:

```markdown
### Timed run (AC3)

- Command: `python3 -I ttft450.py --mod <S>/i450/mod-27450 --proxy-log <S>/i450/runs/proxy-27450.log --cwd <S>/i450/cwd --head «fill: M, short» --out <S>/i450/runs/runs.jsonl`, then `python3 -I analyze450.py --probe-ms «fill: P»`, where `<S>` is the attempt's scratch directory.
- Pairs: «fill: pairs» valid; «fill: invalid_pairs» invalid and replaced («fill: their reasons, or none»). Warm-up attempts: «fill». Reruns: «fill: none, or one, after an invalid first run whose rows are in the sibling». Suspensions: «fill: none, or for each: stopped at <UTC> after <n> valid pairs, resumed at <UTC> after a new warm-up pair».
- The installed service's listener on 27183 had PID «fill: before» before and «fill: after» after.

| Statistic | Value |
|---|---|
| Estimate: median of d = (routed `ttft_ms` + p) − direct `ttft_ms` | «fill: estimate_ms» ms |
| 95% CI, percentile bootstrap, 10,000 resamples, seed 450 | [«fill: ci_ms[0]», «fill: ci_ms[1]»] ms |
| Bound: CI upper end ≤ +100 ms | «fill: within or outside» |

Diagnostics, recorded and never deciding:

- `ttft_ms` quartiles: routed [«fill»], direct [«fill»] ms. Mean of d: «fill» ms.
- Thinking-first: routed «fill»/100, delay «fill» ms; direct «fill»/100, delay «fill» ms (a delay is the arm's median `ttft_ms` of thinking-first runs minus text-first runs, `n/a` when either set is empty).
- Paired medians, routed − direct: harness wall TTFT «fill» ms; startup (wall TTFT − `ttft_ms`) «fill» ms, 95% CI [«fill», «fill»] ms.
- Proxy `ttfb_ms` quartiles over the routed runs: [«fill»] ms.

Per-run rows are in [cache-proxy-ttft-gap-450-runs.md](cache-proxy-ttft-gap-450-runs.md).

«fill: the timed-run line»

### Routing verdict

Issue 450 routing default: «fill: on if the timed-run line says within, else opt-in»

«fill: the verdict sentence» The budget-line export and the `/dev/tcp` probe ship either way.
```

   - The timed-run line is exactly what `jq -r '"Issue 450 timed run: estimate \(.estimate_ms) ms, 95% CI [\(.ci_ms[0]), \(.ci_ms[1])] ms, \(if .within_bound then "within" else "outside" end) the +100 ms bound"' <S>/i450/runs/summary.json` prints.
   - The verdict sentence is, within: `The CI's upper end, «hi» ms, is within the +100 ms bound, so routing is on by default and CLAUDE_CACHE_PROXY=0 opts a launch out (AC4).` Outside: `The CI's upper end, «hi» ms, is over the +100 ms bound, so routing stays opt-in with CLAUDE_CACHE_PROXY=1 (AC4).`
   - No-valid branch: § Timed run (AC3) holds only the Command bullet, a bullet `Two runs at M were invalid: «fill: each run's stop and pair reasons».`, the service bullet, the rows link and the line `Issue 450 timed run: no valid measurement`. The default is `opt-in`, with the sentence `Two runs at M were invalid, so there is no valid measurement and routing stays opt-in (D8, AC4).`
3. Insert the pointer paragraph as the report's line 3, followed by a blank line: `§ Issue 450 below is the current basis for the routing default; the sections before it are #438's point-in-time record.`
4. Fill row `AC3`. Observed: `«pairs» valid pairs («invalid» replaced); estimate «e» ms, 95% CI [«lo», «hi»] ms, «within or outside» the bound; thinking-first routed «k»/100, direct «k»/100`, or `no valid measurement: two invalid runs (report § Timed run (AC3))`. Commit: M, short. Conditions: `host mbp; Claude Code «V»; account p1; M's proxy on 27450; seed 450`.

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; s=docs/spikes/cache-proxy-ttft-gap-450-runs.md
python3 -I <S>/i450/rig/verbatim450.py "$f" --pointer
for m in 'Issue 450 measured head: [0-9a-f]{40}' 'Issue 450 probe term: -?[0-9]+(\.[0-9]+)? ms' \
  'Issue 450 timed run: (estimate -?[0-9.]+ ms, 95% CI \[-?[0-9.]+, -?[0-9.]+\] ms, (within|outside) the \+100 ms bound|no valid measurement)' \
  'Issue 450 routing default: (on|opt-in)'; do
  test "$(grep -Ecx "$m" "$f")" -eq 1
done
t=$(sed -n 's/^Issue 450 timed run: //p' "$f"); d=$(sed -n 's/^Issue 450 routing default: //p' "$f")
case "$t" in *"within the +100 ms bound") test "$d" = on ;; *) test "$d" = opt-in ;; esac
case "$t" in no*) ;; *) test "Issue 450 timed run: $t" = "$(jq -r '"Issue 450 timed run: estimate \(.estimate_ms) ms, 95% CI [\(.ci_ms[0]), \(.ci_ms[1])] ms, \(if .within_bound then "within" else "outside" end) the +100 ms bound"' <S>/i450/runs/summary.json)" ;; esac
for h in '### Timed run (AC3)' '### Routing verdict'; do test "$(grep -cxF "$h" "$f")" -eq 1; done
grep -q '^| warmup |' "$s"
test "$(sed -n 's/^Timed run head: //p' "$s")" = "$(sed -n 's/^Issue 450 measured head: //p' "$f")"
if grep '^| AC[1-3] |' "$A" | grep -q 'pending'; then exit 1; fi
if grep -n '«' "$f" "$s" "$A"; then exit 1; fi
if lsof -nP -iTCP:27450 -sTCP:LISTEN; then exit 1; fi
echo timed-run-recorded
```

Expected: `timed-run-recorded`. At the starting commit, `verbatim450.py --pointer` exits with `no pointer line under the title`. Run the credential scans on the three files, then commit the report, the sibling and `$A` with `launch-commit … -- -m "docs(issue-450): timed run and routing verdict"`, then `rm -rf "$(git rev-parse --git-dir)/issue-450-suspended"`. Report DONE with the estimate, the CI, the verdict and the thinking-first counts. A number is reported as measured and never re-measured to move it (D8).

## Resume (usage limit; D8, D13)

Run this entry, not Steps 0–8, after a `usage_limit` stop. With `H="$(git rev-parse --git-dir)/issue-450-suspended"` and `M` from the report's `Issue 450 measured head:` line, require (timeout 60 s): `tail -n 1 "$H/runs.jsonl" | jq -e '.kind == "usage_limit"'`, `head -n 1 "$H/runs.jsonl" | jq -e --arg m "$M" '.head == $m'`, and a measured-surface check from M to HEAD that prints nothing, with M's pin. A changed surface goes to Task 4's § Re-measurement instead. The suspended run is the first timed run when the report has no `Issue 450 timed run:` line, and a re-measurement when it has one and the sibling's `Timed run head:` differs from M; any other state is BLOCKED (R450-04). Then run Steps 1–4 (a rebuild of M gives byte-identical mod copies; the harness refuses any other), write `M` to `<S>/i450/M`, `cp "$H/runs.jsonl" <S>/i450/runs/runs.jsonl`, and, when `$H/runs.invalid-1.jsonl` exists, `cp "$H/runs.invalid-1.jsonl" <S>/i450/runs/` (R450-02). Run Step 5 with `--resume` and `--routed-switch "$(head -n 1 "$H/runs.jsonl" | jq -r .routed_switch)"` added, so the resumed segment keeps the header's switch, then Steps 6–7. A first timed run then takes Step 8; a re-measurement takes § Re-measurement steps 3–5 instead. Step 8's Suspensions bullet gives, for each `usage_limit` record, its `ts` and the next `resume` record's `ts` in UTC, with the valid-pair count at the stop; its service bullet gives each line of `$H/service-pids` and this segment's PIDs.

## Re-measurement (D4, D15)

Run this entry after Task 4's § Re-measurement has committed a new `Issue 450 measured head:`, so the sibling's `Timed run head:` no longer equals it.

1. If `grep -qxF '    "" | 1) ;;' home/common/claude-code/accounts/bin/claude-account` fails, Task 6 has reverted the switch: add `--routed-switch 1` to Step 5's command, and say so in the record (D13).
2. Run Steps 1–7 at the new M. Step 0's "timed already" refusal does not apply.
3. Under the report's last `### Re-measurement at <short new M>`, add the timed-run statistics with their diagnostics, reruns and suspensions. Replace in place the whole line `Issue 450 timed run:`, rewrite the sibling (with the new `Timed run head:`) and row AC3.
4. Verdict:
   - Switch present: within keeps `on`. Outside, or no valid run, sets `Issue 450 routing default: opt-in` with the opt-in verdict sentence, and Task 6 runs again; it reverts the switch.
   - Opt-in state: outside, or no valid run, keeps `opt-in`, and Task 6 Step 4 runs again to restate the README numbers. Within keeps `opt-in`: commit the record, then report BLOCKED `re-measurement within the bound while routing is opt-in; the owner decides` (D15). In that case only, skip the gate's `case "$t"` consistency line.
5. Run Step 8's gate, then commit with `launch-commit … -- -m "docs(issue-450): re-measurement at <short new M>, timed run"`.
