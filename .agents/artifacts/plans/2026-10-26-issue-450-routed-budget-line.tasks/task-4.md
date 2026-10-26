# Task 4: Measured head, wire check and probe benchmark (AC2)

This task covers spec § Sequence and the measured head (steps 2–3), § Wire check, § Probe benchmark and the first half of § Evidence, per D4, D5, D7, D9, D12, D14 and D15. On mbp it builds the reviewed head and fixes it as M after the version gate. It shows that the budget line is on the routed wire, then measures the probe before against after. It opens `## Issue 450` in #438's report with the root cause, the method that Task 5 must follow, the conditions, the wire check and the AC2 table, and it creates the acceptance record. Task 5 runs the timed run only after this task's record exists. § Re-measurement is this task's half of the new measurement that the measured-surface rule calls for.

**Files:**
- Modify: `docs/spikes/cache-proxy-ttft-gap.md` (append `## Issue 450` with its first five subsections)
- Create: `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` (rows AC1–AC5; this task fills AC1 and AC2)
- Modify only on a version mismatch (Step 3): the comment line in `home/common/claude-code/accounts/bin/claude-account` that ends `verified on Claude Code <X>.`

**Interfaces:**
- Consumes:
  - Tasks 1–3's commits: the reminder export and its comment ending `verified on Claude Code 2.1.310.`; the function `cache_proxy_health`; the case line `    "" | 1) ;;`; and the subject `feat(issue-450): route through the cache proxy by default, CLAUDE_CACHE_PROXY=0 opts out`.
  - `./result` from `just build mbp`, whose closure holds exactly one `-claude-accounts-mod` and one `-org.nix-community.home.claude-cache-proxy.plist`.
  - The issue body's five `- AC<n>: …` lines, and the plan root's § Acceptance map.
- Produces, for Tasks 5 and 6 (D14):
  - The report's whole lines `Issue 450 measured head: <40-hex>` and `Issue 450 probe term: <p> ms`, each exactly once.
  - The headings `### Root cause`, `### Method`, `### Measurement conditions`, `### Budget-line wire check` and `### Probe benchmark (AC2)` under `## Issue 450`.
  - The acceptance record, with row AC3 left `pending Task 5` and rows AC4 and AC5 left `pending Task 6`.

**Invariants:**
- M is the head after Step 3. Every number this task records comes from the outputs of one `just build mbp` of M (D4).
- § Method is committed before any timed pair runs (D14), and no timed pair runs in this task.
- The wire-check runner runs only in Step 5 and the experiment proxy only in Steps 6–8. Each is stopped by pid before this task reports, and nothing listens on 27450 or 27451 at the end. Port 27183 is only listed, never contacted.
- #438's text in the report stays byte-identical: `python3 -I <S>/i450/rig/verbatim450.py docs/spikes/cache-proxy-ttft-gap.md` prints `438-text-verbatim` (D9).
- Nothing under `<S>` or in `$(git rev-parse --git-dir)` is committed.

## Rig files

Step 2 writes these files into `<S>/i450/rig/` with exactly this content. Each was run during planning against a stand-in claude, a local `ProxyServer` and the current build. Task 5 writes the same `mkrig450.sh`, `run-proxy450.sh` and `verbatim450.py`.

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

### `wire450.py`

The wire-check instrument (D7, D12): the built module, with a handler subclass that logs one boolean per request.

```python
"""Wire check (issue 450 D7): M's cache-proxy, logging for each POST /v1/messages only whether
its body (gzip-decoded when sent gzipped) contains `<total_tokens>`. No body bytes are kept.

<interpreter> -I wire450.py --port 27451   (the interpreter M's cache-proxy launcher execs)
"""
import gzip
import sys
from urllib.parse import urlsplit

from agent_tools import cache_proxy


class WireHandler(cache_proxy.ProxyHandler):
    def _read_body(self, started):
        body = super()._read_body(started)
        if body is not None and self.command == "POST" and urlsplit(self.path).path == "/v1/messages":
            encoding = (self.headers.get("Content-Encoding") or "identity").strip().lower()
            if encoding == "gzip":
                body_text = gzip.decompress(body)
            elif encoding == "identity":
                body_text = body
            else:
                body_text = None
            self.server.log.write("wire_check", encoding=encoding,
                                  total_tokens=None if body_text is None else b"<total_tokens>" in body_text)
        return body


cache_proxy.ProxyHandler = WireHandler  # ProxyServer looks the handler class up when it is built
sys.exit(cache_proxy.main(sys.argv[1:]))
```

### `bench450.py`

The AC2 benchmark (D5, D12).

```python
"""AC2 probe benchmark (issue 450 D5): paired wall time of `claude-account run`, routed - direct.

python3 -I bench450.py --before DIR --after DIR --proxy-url URL --scratch DIR --out FILE [--pairs 200]
Each DIR is a mod copy whose bin/claude-account is the version under test. Runs take the early
exec (a scratch CLAUDE_CONFIG_DIR) with `env` standing in for claude, so no profile is touched.
"""
import argparse, json, os, shutil, statistics, subprocess, sys, time


def run(script, switch, scratch):
    env = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    env.update(HOME=os.path.join(scratch, "home"), CLAUDE_ACCOUNTS_DIR=os.path.join(scratch, "accounts"),
               CLAUDE_CONFIG_DIR=os.path.join(scratch, "config"), CLAUDE_BIN=shutil.which("env"),
               CLAUDE_CACHE_PROXY=switch)
    started = time.perf_counter_ns()
    done = subprocess.run([script, "run"], env=env, capture_output=True, text=True, timeout=30, check=False)
    elapsed = (time.perf_counter_ns() - started) / 1e6
    base = [line for line in done.stdout.splitlines() if line.startswith("ANTHROPIC_BASE_URL=")]
    return elapsed, done.returncode, base


def summary(diffs):
    q1, q2, q3 = statistics.quantiles(diffs, n=4)
    return {"n": len(diffs), "median_ms": round(statistics.median(diffs), 3),
            "q1_ms": round(q1, 3), "q3_ms": round(q3, 3), "iqr_ms": round(q3 - q1, 3)}


def main():
    parser = argparse.ArgumentParser()
    for name in ("--before", "--after", "--proxy-url", "--scratch", "--out"):
        parser.add_argument(name, required=True)
    parser.add_argument("--pairs", type=int, default=200)
    args = parser.parse_args()
    for sub in ("home", "accounts", "config"):
        os.makedirs(os.path.join(args.scratch, sub), exist_ok=True)
    versions = {"before": os.path.join(args.before, "bin", "claude-account"),
                "after": os.path.join(args.after, "bin", "claude-account")}
    diffs = {name: [] for name in versions}
    invalid = []
    for index in range(args.pairs):
        names = ["before", "after"] if index % 2 == 0 else ["after", "before"]
        arms = ["1", "0"] if index % 2 == 0 else ["0", "1"]
        for name in names:
            times = {}
            for switch in arms:
                elapsed, code, base = run(versions[name], switch, args.scratch)
                expected = ["ANTHROPIC_BASE_URL=" + args.proxy_url] if switch == "1" else []
                if code != 0 or base != expected:
                    invalid.append({"pair": index, "version": name, "switch": switch, "exit": code, "base": base})
                times[switch] = elapsed
            diffs[name].append(times["1"] - times["0"])
    result = {"pairs": args.pairs, "valid": not invalid, "invalid": invalid[:20],
              "proxy_url": args.proxy_url, **{name: summary(values) for name, values in diffs.items()}}
    result["met"] = result["valid"] and result["after"]["median_ms"] < result["before"]["median_ms"]
    with open(args.out, "w") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({key: result[key] for key in ("valid", "met")} |
                     {name: result[name]["median_ms"] for name in versions}))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
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

`<S>/i450` holds the rig outputs and `<S>/i450/runs` the raw results. `A=.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` is the acceptance record.

- [ ] **Step 0: Preconditions**

Run (timeout 30 s):

```bash
set -euo pipefail
w=home/common/claude-code/accounts/bin/claude-account
grep -qF 'export CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown' "$w"
grep -q '^cache_proxy_health() {$' "$w"
grep -qxF '    "" | 1) ;;' "$w"
git log --format=%s 51e2b7c9..HEAD | grep -qxF 'feat(issue-450): route through the cache proxy by default, CLAUDE_CACHE_PROXY=0 opts out'
if grep -Eq '^Issue 450 (measured head|routing default):' docs/spikes/cache-proxy-ttft-gap.md; then echo 'measured already: Task 5 continues, or § Re-measurement'; exit 1; fi
echo preconditions-ok
```

Any failure is BLOCKED, with the output.

- [ ] **Step 1: Build**

Run (timeout 3600 s): `launch-scope exec … -- just build mbp`. Expected: exit 0.

- [ ] **Step 2: Rig**

Write § Rig files into `<S>/i450/rig/`. Then run (timeout 300 s): `bash <S>/i450/rig/mkrig450.sh "$PWD" <S>/i450`. Expected: `mkrig450: V=<V>`, plus `<S>/i450/conditions.env` and the copies `mod-27450`, `mod-27451` and `before`. An error is BLOCKED with its message.

- [ ] **Step 3: Version gate (D7)**

Run (timeout 60 s):

```bash
set -euo pipefail
. <S>/i450/conditions.env
X=$(sed -nE 's/.*verified on Claude Code ([0-9][0-9.]*[0-9]).*/\1/p' home/common/claude-code/accounts/bin/claude-account)
python3 -I -c 'import sys; sys.exit(tuple(map(int, sys.argv[1].split("."))) < (2, 1, 310))' "$V"
echo "comment $X, built $V"; test "$X" = "$V"
```

- If `V` is below 2.1.310, report BLOCKED `claude-code below 2.1.310: <V>`.
- If `X` differs from `V`, change only that comment's version to `V` and run the focused tests (`OK`, 17 tests while `    "" | 1) ;;` is in `claude-account`; 18 once Task 6 has reverted the switch). Commit it with `launch-commit … -- -m "fix(issue-450): the budget-line comment names Claude Code <V>"`, then go back to Step 1. This is the one change allowed before M is fixed (spec § Sequence, step 2).
- If they are equal: `git rev-parse HEAD > <S>/i450/M`. That head is M.

- [ ] **Step 4: Ports and the service**

Run (timeout 30 s): `for p in 27450 27451; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done; lsof -nP -t -iTCP:27183 -sTCP:LISTEN > <S>/i450/service-pid.before || true`. A busy port is BLOCKED. An empty service pid is recorded as `none`.

- [ ] **Step 5: Wire check (D7)**

Start the runner with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh <S>/i450/rig/run-proxy450.sh <S>/i450 wire 27451 <S>/i450/runs/wire-27451.log`. Await it (timeout 60 s): `curl -q --noproxy '*' -fsS -o /dev/null --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27451/_proxy/health`.

Run one routed session (timeout 300 s):

```bash
cd <S>/i450/cwd && launch-scope exec … -- env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" PATH="$PATH" TMPDIR="$TMPDIR" SHELL="$SHELL" TERM="${TERM:-dumb}" ${LANG:+LANG="$LANG"} ${LC_ALL:+LC_ALL="$LC_ALL"} CLAUDE_ACCOUNT=p2 CLAUDE_CODE_EMIT_STARTUP_TIMING=1 <S>/i450/mod-27451/bin/claude-account run -p --model haiku --output-format stream-json --verbose --include-partial-messages "Reply with exactly: ok" > <S>/i450/runs/wire-session.jsonl
```

Stop the runner: `kill "$(cat <S>/i450/wire-27451.pid)"`, then one `sleep 2`, then `if lsof -nP -iTCP:27451 -sTCP:LISTEN; then exit 1; fi`. Read the outcome (timeout 30 s):

```bash
jq -c 'select(.type == "result") | {is_error, api_error_status}' <S>/i450/runs/wire-session.jsonl
jq -cs '[.[] | select(.event == "wire_check")] | {n: length, k: (map(select(.total_tokens == true)) | length), encodings: (map(.encoding) | unique)}' <S>/i450/runs/wire-27451.log
```

- A result with `is_error` and `api_error_status` 429, or limit text: report BLOCKED with `blocked_on=usage_limit` (D13).
- `n` is 0: report BLOCKED `wire check: the session was not routed`, with both outputs.
- `k` is 0: report BLOCKED `wire check: no <total_tokens> on the routed wire on Claude Code <V>`. The work returns to the owner (D7).
- `k ≥ 1`: the line is present. Keep `k`, `n` and the encodings for Step 9.

- [ ] **Step 6: Experiment proxy**

Start it with `run_in_background: true`: `launch-scope exec … -- sh <S>/i450/rig/run-proxy450.sh <S>/i450 proxy 27450 <S>/i450/runs/proxy-27450.log`. Await it as in Step 5, on port 27450.

- [ ] **Step 7: Probe benchmark (AC2, D5)**

Run (timeout 1800 s): `launch-scope exec … -- python3 -I <S>/i450/rig/bench450.py --before <S>/i450/before --after <S>/i450/mod-27450 --proxy-url http://127.0.0.1:27450 --scratch <S>/i450/bench --out <S>/i450/runs/bench.json`. It prints `{"valid", "met", "before", "after"}`.

- Exit 1 (`valid` false): run Step 8, then report BLOCKED with `jq -c .invalid <S>/i450/runs/bench.json`.
- `met` false: run Step 8, then report BLOCKED `probe benchmark missed: before <b> ms, after <a> ms`. The controller routes one fix to Task 2's files, and this task then restarts at Step 0 on the new head (D4).
- `met` true: `P=$(jq -r '.after.median_ms * 10 | round / 10' <S>/i450/runs/bench.json)`.

- [ ] **Step 8: Stop and check**

Run (timeout 30 s): `kill "$(cat <S>/i450/proxy-27450.pid)"`, then one `sleep 2`, then `for p in 27450 27451; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done; lsof -nP -t -iTCP:27183 -sTCP:LISTEN > <S>/i450/service-pid.after || true; cmp <S>/i450/service-pid.before <S>/i450/service-pid.after && echo service-unchanged`. A port still listening is BLOCKED. A changed service PID is recorded with both values in § Measurement conditions and reported as DONE_WITH_CONCERNS: this task never contacts 27183.

- [ ] **Step 9: Record the measured head, the wire check and the benchmark**

Append the text below to the report, after one blank line. Fill each `«fill: …»` from `<S>/i450/conditions.env`, `<S>/i450/M`, Steps 5 and 8, `bench.json` (`before` and `after`: `median_ms`, `q1_ms`, `q3_ms`, `iqr_ms`) and `P`:

```markdown
## Issue 450

Re-measurement for https://github.com/fagenorn/nix-config/issues/450, by the plan .agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.md. The sections above are #438's record and stand as written; this section corrects its method and holds the current measurement.

### Root cause

The 2026-10-26 investigation on Claude Code 2.1.310 (mbp, account `p1`; its full report is reproduced in the issue) found:

- The proxy hop adds no measurable time to first token. Pooled over 130 pairs, proxied minus direct was −63 ms mean (95% CI −182 to +55), and the same request bytes took 1364 ms through the proxy against 1432 ms straight to the API (n = 80).
- Server latency follows the session (`metadata.user_id.session_id`): swapping only the session id moves one request by about ±700 ms. A 10-pair rule then has a noise band of about ±245–300 ms and cannot resolve 100 ms.
- One effect is real. Claude Code sends the `<total_tokens>N tokens left</total_tokens>` line only to api.anthropic.com. Without it the model opened with a thinking block 45–58% of the time, against 5–12% direct, and its first token came 0–580 ms later. `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` restores the identical line on the wire, and routed launches now export it.
- The wrapper's curl-and-jq health probe added 27 ms to every routed launch. The probe now uses bash's `/dev/tcp`.

### Method

#438 decided on 10 pairs, by the difference of the per-arm medians of harness-side TTFT, with one confirmation run, against a noise band of ±245–300 ms; its numbers stand as recorded above. The rule below replaces that method, and it was committed before any timed pair ran:

- Each run is a fresh `claude -p` session launched through the built wrapper: routed with `CLAUDE_CACHE_PROXY` unset, direct with `CLAUDE_CACHE_PROXY=0`, and nothing else different. The order flips each pair. One warm-up pair is discarded, then exactly 100 valid pairs count.
- Per pair, d = (routed `ttft_ms` + p) − direct `ttft_ms`, where `ttft_ms` is the client's own and p is the probe term of § Probe benchmark (AC2).
- The estimate is the median of d. Its 95% CI is a percentile bootstrap over pairs, 10,000 resamples, seed 450. Routed is within the bound when the CI's upper end is ≤ +100 ms, and that alone sets the routing default.
- A pair counts when both runs exit 0 with a `ttft_ms` and a first content block of `thinking`, `redacted_thinking` or `text`, and the routed run has exactly one proxy `/v1/messages` line and the direct run none. An invalid pair is replaced at the end. An 11th invalid pair makes the run invalid; it is rerun once, and a second invalid run means no valid measurement. A usage limit suspends the run, which resumes at the same head after a new warm-up pair. The run is never extended.
- Diagnostics are recorded and never decide.

### Measurement conditions

- Date «fill: date -u +%F», host `mbp`, account `p2` (by name only; p1 was on its weekly usage limit, so the user chose p2, D17), Claude Code «fill: V» (`«fill: CLAUDE_BIN_PATH»`).
- Built from M: wrapper module `«fill: MOD»`, agent plist `«fill: PLIST»`, launcher `«fill: LAUNCHER»`, interpreter `«fill: INTERP»`, CA bundle `«fill: CA»`.
- Experiment proxy on 27450: the launcher with `--port 27450 --keepalive` and `SSL_CERT_FILE` as the service sets it. Wire-check runner on 27451. The installed service on 27183 was only listed: its listener's PID was «fill: service-pid.before, or none» before the benchmark and «fill: service-pid.after, or none» after it.
- Bootstrap seed 450, 10,000 resamples.

Issue 450 measured head: «fill: M»

### Budget-line wire check

One routed `claude -p` session on the timed command line, through a copy of M's mod pointed at 27451 and the wire-check runner, which logs per request only whether the body contains `<total_tokens>`: «fill: k» of «fill: n» `/v1/messages` requests carried it (body encodings: «fill: encodings»). The line is on the routed wire on Claude Code «fill: V».

### Probe benchmark (AC2)

`claude-account run` wall time, routed (`CLAUDE_CACHE_PROXY=1`) minus direct (`0`), over 200 pairs per version, with before and after interleaved and both orders flipping each pair. Each run takes the early exec, with `env` standing in for claude and the experiment proxy answering health.

| Version | Launcher | Pairs | Median increment ms | Quartiles ms | IQR ms |
|---|---|---|---|---|---|
| before | `claude-account` at `51e2b7c9` under M's substitutions | 200 | «fill» | [«fill», «fill»] | «fill» |
| after | M's built `claude-account` | 200 | «fill» | [«fill», «fill»] | «fill» |

AC2 met: after's median increment is below before's, and the routing tests' fail-to-direct cases pass at M.

Issue 450 probe term: «fill: P» ms
```

Create the acceptance record (timeout 60 s):

```bash
gh issue view 450 --repo fagenorn/nix-config --json body -q .body > <S>/i450/issue-body.md
python3 -I - <S>/i450/issue-body.md .agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.md > "$A" <<'PY'
import re, sys
body, plan = open(sys.argv[1]).read(), open(sys.argv[2]).read()
criteria = re.findall(r"^- (AC[1-5]: .*)$", body, re.M)
checks = re.findall(r"^\| (AC[1-5]) \| [^|]+ \| Task \d \| (.*) \|$", plan, re.M)
assert [c[:3] for c in criteria] == [a for a, _ in checks] == ["AC1", "AC2", "AC3", "AC4", "AC5"]
kinds = {"AC1": "code", "AC2": "evidence", "AC3": "evidence", "AC4": "code", "AC5": "code"}
print("# Acceptance record — issue #450\n")
print("Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/450).\n")
print("| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |")
print("|----|-----------|------|------------------|----------|--------|------------|---------|")
for criterion, (ac, check) in zip(criteria, checks):
    owner = {"AC1": "Task 4", "AC2": "Task 4", "AC3": "Task 5"}.get(ac, "Task 6")
    print(f"| {ac} | {criterion} | {kinds[ac]} | {check} | pending {owner} | — | — | — |")
PY
```

Fill rows `AC1` and `AC2` (Observed, Commit, Conditions); the controller writes `Verdict`:
- AC1: Observed `in final verification; wire check: «k» of «n» routed /v1/messages requests carried the total_tokens line on Claude Code «V»`. Commit: M, short. Conditions: `host mbp; account p2; wire-check runner on 27451`.
- AC2: Observed `median increment before «b» ms, after «a» ms (IQR «before iqr», «after iqr» ms); valid; after < before`. Commit: M, short. Conditions: `host mbp; Claude Code «V»; M's proxy on 27450; 200 interleaved pairs per version; early exec with env for claude`.

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md
python3 -I <S>/i450/rig/verbatim450.py "$f"
test "$(grep -cx "Issue 450 measured head: $(cat <S>/i450/M)" "$f")" -eq 1
test "$(grep -Ecx 'Issue 450 probe term: -?[0-9]+(\.[0-9]+)? ms' "$f")" -eq 1
for h in '### Root cause' '### Method' '### Measurement conditions' '### Budget-line wire check' '### Probe benchmark (AC2)'; do test "$(grep -cxF "$h" "$f")" -eq 1; done
test "$(grep -c '^| AC[1-5] |' "$A")" -eq 5
if grep '^| AC[12] |' "$A" | grep -q 'pending'; then exit 1; fi
if grep -n '«' "$f" "$A"; then exit 1; fi
echo part-1-recorded
```

Expected: `part-1-recorded`. At the starting commit `verbatim450.py` exits with `no ## Issue 450 section`. Run the Global Constraints' credential scans on both files, then commit `docs/spikes/cache-proxy-ttft-gap.md` and `$A` with `launch-commit … -- -m "docs(issue-450): measured head, wire check and probe benchmark"`. Report DONE with V, M, both medians and P.

## Re-measurement (D4, D15)

Run this entry when § Issue 450 exists and the Global Constraints' measured-surface check against its M prints a change, or the pin moved (a review fix, a ship sync). If nothing changed, report DONE `no re-measurement due`.

1. Rename any `$(git rev-parse --git-dir)/issue-450-suspended` to `issue-450-superseded-<short M>`.
2. Run Steps 1–8 at the new head. Step 3 may correct the comment again; the new M is the head after it. Step 0's "measured already" refusal does not apply. If `grep -qxF '    "" | 1) ;;' home/common/claude-code/accounts/bin/claude-account` fails, Task 6 has reverted the switch and routing is opt-in: add `CLAUDE_CACHE_PROXY=1` after `CLAUDE_ACCOUNT=p2` in Step 5's routed session, and say so in the re-measurement record (R450-03).
3. Append at the end of the report `### Re-measurement at <short new M>`, holding in prose Step 9's conditions bullets, the wire-check result, the AC2 table and the sentence `This re-measurement binds; the measurement above it is superseded (D4). Its timed run follows below.` Replace in place the whole lines `Issue 450 measured head:` and `Issue 450 probe term:`, so each still occurs once. Rewrite the wire-check part of row AC1, and row AC2.
4. Run Step 9's gate, giving `verbatim450.py` `--pointer` when the report already has the pointer paragraph. Commit with `launch-commit … -- -m "docs(issue-450): re-measurement at <short new M>, benchmark"`. Task 5's § Re-measurement then runs the timed run.
