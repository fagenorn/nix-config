# Task 5: AC4 evidence — the A/B pipeline eval

Spec § Evidence runs (AC4), per D5, D6, D18 and D23, under #422 D27. On mbp, `just evals from-issue 1` runs once against a built-launcher instance on `--port 0` with `--keepalive --reorder`, then once with `--keepalive` alone. In both, the built `claude` wrapper is first on `PATH` and the root's **Routed-launch environment** points at that arm's instance; nothing else differs. Each run is costed at list price through `just agent-costs --format json` over an isolated copy of its own transcripts. The evals append their lines to the tracked `results.jsonl`, which this task commits. A FAIL or a higher cost is recorded as observed, never tuned or rerun toward a pass (#422 D27).

**Files:**
- Modify: `docs/spikes/cache-proxy-prefix-retest.md` (append `## AC4 evidence — A/B eval`; every earlier line stays as committed, D10)
- Modify: `.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md` (row `AC4`)
- Modify (appended by the runs): `home/common/agent-skills/evals/results/results.jsonl`
- Modify, only when the report would pass 65,536 bytes: `docs/spikes/cache-proxy-prefix-retest-2-usage.md` (D25)
- Scratch only: `$S/i429/ac4/`

**Interfaces:**
- Consumes (Task 3, via `./result`): the plist whose `ProgramArguments.2` is `/bin/wait4path /nix/store && exec <launcher> --port 27183 --keepalive --reorder`, its `SSL_CERT_FILE`, and `<hash>-claude-code-with-accounts-<version>/bin/claude`; `request` lines carry `reorder` only under `--reorder`, and `ping` lines carry `usage`.
- Consumes: `just evals from-issue 1` (`home/common/agent-skills/evals/run-eval.sh`), which resolves `claude` from `PATH`, sets `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1` itself, prints `workdir: <WORK>` (the sandbox repo is `<WORK>/repo`), `PASS  <assert>`/`FAIL  <assert>` lines and one `VERDICT: …` line, and appends one JSON line (`ts`, `skill`, `id`, `verdict`, `wall_s`, `workdir`, `cost_usd`, …) to `results.jsonl`. Its default timeout is 2,700 s.
- Consumes: `just agent-costs --format json --days 0 --projects-dir <dir>`, whose record holds `.strata.claude.cost_basis` (`list-price`) and `.strata.claude.totals.cost_usd`; the acceptance row `AC4` reading `pending (Task 5)`.
- Produces: row `AC4`'s evidence columns; up to two `results.jsonl` lines (none for an arm skipped at the cutoff); the appended section.

**Invariants:**
- No `just switch`, `launchctl` or `systemctl`; the installed service on 27183 is never stopped, reconfigured or connected to. Each instance this task starts is stopped by its pid before the next arm and before the task reports.
- The two runs differ only in `--reorder`. No `EVAL_TREE` is set; the eval's default model and timeout apply.
- The on arm's log gains at least one line containing `"reorder":"applied"`; the off arm's has no `"reorder"`; each has a `"path":"/v1/messages` line.
- Every eval line stays in `results.jsonl`, a failed one included; nothing is deleted.

- [ ] **Step 1: Check the starting state**

Run (timeout 30 s):

```bash
set -e
test "$(hostname -s)" = mbp
test -z "$(git status --short)"
grep -qx 'Attempt 2 verdict: go' docs/spikes/cache-proxy-prefix-retest.md
grep -q '^| AC4 |.*pending (Task 5)' .agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
git rev-parse HEAD; wc -l < home/common/agent-skills/evals/results/results.jsonl
```

Record `CODE_HEAD` and the line count `LINES0`.

**Deadline cutoff (D23).** Before each arm, compute the minutes left (root § Deadline); an arm runs only with at least 50. A skipped arm is not run. Row `AC4` then reads `<arm> not run: attempt deadline cutoff (human-pending)` for it, with its exact Step 3 command in `Conditions`, and the report section says the same; a ran on arm's result is still recorded, and with the off arm skipped, the cost comparison is `human-pending` too.

- [ ] **Step 2: Build and locate**

Run (timeout 3600 s): `launch-scope exec … -- just build`. Then (timeout 60 s) locate the outputs exactly as below and write the scripts:

```bash
set -euo pipefail
E=$S/i429/ac4; mkdir -p "$E"
closure=$(nix-store -qR ./result)
one() { hits=$(printf '%s\n' "$closure" | grep -E -- "$1" || true); test "$(printf '%s\n' "$hits" | grep -c .)" -eq 1; printf '%s\n' "$hits"; }
one '-claude-code-with-accounts-[0-9.]+$' > "$E/pkg"
plist=$(one '-org\.nix-community\.home\.claude-cache-proxy\.plist$')
plutil -extract ProgramArguments.2 raw -o - "$plist" | sed -nE 's|^/bin/wait4path /nix/store && exec (/nix/store/[^ ]+-agent-tools-cache-proxy) --port 27183 --keepalive --reorder$|\1|p' > "$E/launcher"
test -s "$E/launcher"
plutil -extract EnvironmentVariables.SSL_CERT_FILE raw -o - "$plist" > "$E/ca"; test -s "$(cat "$E/ca")"
cat > "$E/run-proxy.sh" <<'EOF'
#!/bin/sh
# The built cache-proxy launcher in the foreground on a free port (#429 D23).
# run-proxy.sh <log> <pidfile> <ca bundle> <launcher> [flags...]
log=$1 pidfile=$2 ca=$3 launcher=$4; shift 4
echo $$ > "$pidfile"
exec env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin SSL_CERT_FILE="$ca" "$launcher" --port 0 "$@" >>"$log" 2>&1
EOF
cat > "$E/eval.sh" <<'EOF'
#!/usr/bin/env bash
# One AC4 arm (#429 D23): eval.sh <arm> <E> <pkg> <port>; that arm's instance is already running.
set -uo pipefail
arm=$1 E=$2 pkg=$3 port=$4
start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
env -u PYTHONPATH PATH="$pkg/bin:$PATH" ANTHROPIC_BASE_URL="http://127.0.0.1:$port" \
  ENABLE_TOOL_SEARCH=true CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown CLAUDE_ACCOUNT=p2 \
  just evals from-issue 1 > "$E/eval-$arm.txt" 2>&1
status=$?
end=$(python3 -I -c 'import datetime as d; print((d.datetime.now(d.timezone.utc) + d.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))')
printf '%s %s %s\n' "$start" "$end" "$status" > "$E/eval-$arm.window"
echo "eval $arm exit $status window $start $end"
EOF
```

Also write `$E/copy.py`, a short standard-library script taking `<repo> <dest> <start>`: for every `$HOME/.claude-accounts/profiles/p2/projects/<dir>/<session>.jsonl` modified at or after `<start>` that holds a record whose `cwd` is `<repo>` or under `<repo>/` (the eval sandbox and its worktrees), it copies that file and its sibling `<session>/` directory into `<dest>/<dir>/`, and it exits non-zero when it copies nothing.

- [ ] **Step 3: The on arm (timeout 3600 s)**

Start the proxy with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh $E/run-proxy.sh $E/proxy-on.log $E/proxy.pid "$(cat $E/ca)" "$(cat $E/launcher)" --keepalive --reorder`. Run one bounded `sleep 3`, then read `port` from the log's first line, which must be a `listening` line with `"keepalive":true` and `"reorder":true` and a port other than 27183, 8160, 4322, 27450 and 27451 (else stop it and report BLOCKED with the line). `curl -q --noproxy '*' -fsS --max-time 2 --retry 5 --retry-connrefused http://127.0.0.1:<port>/_proxy/health` must print `{"service":"cache-proxy","status":"ok"}`. Run in the foreground: `launch-scope exec … -- bash $E/eval.sh on $E "$(cat $E/pkg)" <port>`. Stop the proxy (`kill "$(cat $E/proxy.pid)"`) and check that its health probe no longer answers.

A run that ends with a `VERDICT:` line in `$E/eval-on.txt` is a recorded result, whatever its exit code. One without (an outage or harness death) is an instrument failure and may be rerun once if the cutoff allows, both attempts recorded. A usage-limit refusal (`"status":429` in the log, or the eval's output naming the limit) stops the task: report BLOCKED `blocked_on=usage_limit`, with nothing committed and `$E` left in place.

- [ ] **Step 4: The off arm (timeout 3600 s)**

Repeat Step 3 with `$E/proxy-off.log`, the flags `--keepalive` alone (the `listening` line has no `reorder`), and the arm `off`.

- [ ] **Step 5: Read the runs**

```bash
for arm in on off; do
  [ -e "$E/eval-$arm.window" ] || continue
  read -r start end status < "$E/eval-$arm.window"
  work=$(sed -n 's/^workdir: //p' "$E/eval-$arm.txt" | tail -1); test -n "$work"
  grep -E '^(PASS|FAIL)  |^VERDICT:' "$E/eval-$arm.txt"
  rm -rf "$E/$arm-projects"
  python3 -I "$E/copy.py" "$work/repo" "$E/$arm-projects" "$start"
  just agent-costs --format json --days 0 --projects-dir "$E/$arm-projects" > "$E/cost-$arm.json"
  jq -e '.strata.claude.cost_basis == "list-price" and .strata.claude.totals.runs >= 1' "$E/cost-$arm.json"
  jq -r '.strata.claude.totals.cost_usd' "$E/cost-$arm.json"
  grep -c '"path":"/v1/messages' "$E/proxy-$arm.log" || true
  grep -c '"reorder":"applied"' "$E/proxy-$arm.log" || true
  grep -c '"reorder"' "$E/proxy-$arm.log" || true
  grep '"event":"ping"' "$E/proxy-$arm.log" | jq -c '{conversation, status, outcome, usage}' || true
done
r=home/common/agent-skills/evals/results/results.jsonl
tail -n "$(( $(wc -l < "$r") - LINES0 ))" "$r" | jq -c '{ts, skill, id, verdict, wall_s, workdir, cost_usd}'
```

Each appended line has `skill` `from-issue` and `id` `1`, and its `workdir` matches its run's `workdir:` line. A proxy count that misses the arm invariants makes that arm void, recorded and not counted. Thresholds (AC4): the on `VERDICT:` is `PASS`, and the on `agent-costs` `cost_usd` is ≤ the off one. Each arm's `ping` lines and their usage are reported beside its cost and do not gate (D18).

- [ ] **Step 6: Record**

Append to `docs/spikes/cache-proxy-prefix-retest.md`, after one blank line, a section `## AC4 evidence — A/B eval` holding: the sentence `Appended by Task 5; the sections above are unchanged (D10).`; one table `| Arm | VERDICT | Asserts | agent-costs list-price USD | results.jsonl cost_usd | ts | wall_s | Proxy lines | Pings |` (a skipped arm's row reads `not run: attempt deadline cutoff (human-pending)`); the `PASS`/`FAIL`/`VERDICT` lines of each run in one fenced `text` block and its appended `results.jsonl` lines in one fenced `json` block; and the conditions: host, `CODE_HEAD`, account `p2`, the wrapper and launcher paths with flags, each instance's port, both windows and commands, and any rerun or cutoff. If the report would pass 65,536 bytes, the fenced blocks go unchanged to the usage file under `## AC4 eval output`, linked from the section (D25).

Fill row `AC4`: `Observed` `on <VERDICT line> (PASS: met|missed); list-price cost on <x> vs off <y> USD (on ≤ off: met|missed); pings on <n>, off <m>`; `Commit` `CODE_HEAD`'s short SHA; `Conditions` host `mbp`, account `p2`, wrapper and launcher paths, both windows, both `workdir` values, `one trial per arm, not rerun toward a pass (#422 D27)`. `Verdict` stays `—`. When a threshold is missed, report DONE_WITH_CONCERNS naming it.

- [ ] **Step 7: Verify**

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-prefix-retest.md
a=.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
r=home/common/agent-skills/evals/results/results.jsonl
test "$(grep -cx '## AC4 evidence — A/B eval' "$f")" -eq 1
if grep -q 'pending (Task 5)' "$a"; then exit 1; fi
grep -Eq '^\| AC4 \|.*(on VERDICT:|not run: attempt deadline cutoff)' "$a"
test "$(grep -Ec '^Attempt 2 (billing suffix|gain|verdict): ' "$f")" -eq 3
for p in "$f" docs/spikes/cache-proxy-prefix-retest-2-*.md; do test "$(wc -c < "$p")" -le 65536; done
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a" docs/spikes/cache-proxy-prefix-retest-2-*.md; then exit 1; fi
ran=$(find "$E" -maxdepth 1 -name 'eval-*.window' | wc -l | tr -d ' ')
added=$(( $(wc -l < "$r") - LINES0 ))
if [ "$ran" -eq 0 ]; then
  test "$added" -eq 0; git diff --quiet -- "$r"
else
  test "$added" -ge 1 && test "$added" -le 3
  test "$(git diff --numstat -- "$r" | cut -f2)" = 0
fi
git diff --quiet "$CODE_HEAD" -- home/common/claude-code lib justfile python tests flake.lock
echo ac4-recorded
```

Expected: `ac4-recorded`. At the starting commit it fails at the first `test`, because there is no AC4 section. The `results.jsonl` checks follow the arms that ran: with both skipped, nothing is appended and the file is unchanged.

- [ ] **Step 8: Commit**

```bash
git add docs/spikes/cache-proxy-prefix-retest.md docs/spikes/cache-proxy-prefix-retest-2-usage.md .agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md home/common/agent-skills/evals/results/results.jsonl
launch-commit … -- -m "docs(spike): AC4 A/B eval evidence, reorder on and off (issue 429)" -m "<session trailers>"
```

Before reporting, check that every instance this task started is gone and that `git status --short` prints nothing.
