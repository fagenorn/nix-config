# Task 4: AC3 evidence — sibling 2's start-up read, on and off

Spec § Evidence runs (AC3), per D5, D6, D22 and D23, under #422 D27. On mbp, two instances of the closure's built (never activated) `cache-proxy` launcher run in the foreground on `--port 0`, first `--keepalive --reorder`, then `--keepalive` alone. Each arm is one parent run of the root's **Parent prompt** from a new scratch worktree, through the built `claude` wrapper, under the root's **Routed-launch environment** pointed at that arm's instance. Each run is read with `just agent-costs --report cache` over an isolated copy of its own transcripts, windowed to sibling 2's first call. No code changes: a missed threshold is recorded as observed, never tuned or rerun (#422 D27).

**Files:**
- Modify: `docs/spikes/cache-proxy-prefix-retest.md` (append `## AC3 evidence — shared prefix`; every earlier line stays as committed, D10)
- Modify: `.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md` (row `AC3`)
- Modify, only when the report would pass 65,536 bytes: `docs/spikes/cache-proxy-prefix-retest-2-usage.md` (D25)
- Scratch only: `$S/i429/ac3/`

**Interfaces:**
- Consumes (Task 3, via `./result` after `just build`): the plist `<hash>-org.nix-community.home.claude-cache-proxy.plist`, whose `ProgramArguments.2` is `/bin/wait4path /nix/store && exec <launcher> --port 27183 --keepalive --reorder` and whose `EnvironmentVariables.SSL_CERT_FILE` is the CA bundle; the wrapper `<hash>-claude-code-with-accounts-<version>/bin/claude`; the `listening` line's `port`, and `request` lines carrying `reorder` only under `--reorder`.
- Consumes: `agent_tools.agent_cache_report.transcript_jobs(root, None)` and `scan_transcript((path, is_root), since=<datetime>, before=<datetime>, threshold=agent_cache_report.DEFAULT_CONTEXT_THRESHOLD)`, whose `startup` is `{"write", "read", "attachments"}` or `None`; `agent_tools.agent_costs.parse_rfc3339_utc`; the acceptance row `AC3` reading `pending (Task 4)`.
- Produces: row `AC3`'s evidence columns and the appended section.

**Invariants:**
- No `just switch`, `launchctl` or `systemctl`; the installed service on 27183 is never stopped, reconfigured or connected to. Each instance this task starts is stopped by its pid before the next arm and before the task reports.
- The arms differ only in `--reorder`, each with a new worktree and nonce, both under `CLAUDE_ACCOUNT=p2`.
- The on arm's proxy log has at least one line containing `"reorder":"applied"`; the off arm's has no `"reorder"` at all; both have a `"path":"/v1/messages` line.
- The report's earlier lines and the acceptance rows other than `AC3` are unchanged.

- [ ] **Step 1: Check the starting state**

Run (timeout 30 s), from the worktree root:

```bash
set -e
test "$(hostname -s)" = mbp
test -z "$(git status --short)"
grep -qx 'Attempt 2 verdict: go' docs/spikes/cache-proxy-prefix-retest.md
grep -q '^| AC3 |.*pending (Task 4)' .agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
git rev-parse HEAD
```

Record `CODE_HEAD` (the printed SHA).

**Deadline cutoff (D23).** Before each arm, compute the minutes left (root § Deadline); an arm runs only with at least 15. A skipped arm is not run and has no `summary.json`. Its half of row `AC3`'s `Observed` reads `<arm> not run: attempt deadline cutoff (human-pending)`, and its exact commands from Steps 3–5 go in `Conditions`; the report section says the same. Steps 6–8 cover only the arms that ran.

- [ ] **Step 2: Build and locate the built outputs**

Run (timeout 3600 s): `launch-scope exec … -- just build`. Then (timeout 60 s):

```bash
set -euo pipefail
E=$S/i429/ac3; mkdir -p "$E"
closure=$(nix-store -qR ./result)
one() { hits=$(printf '%s\n' "$closure" | grep -E -- "$1" || true); test "$(printf '%s\n' "$hits" | grep -c .)" -eq 1; printf '%s\n' "$hits"; }
one '-claude-code-with-accounts-[0-9.]+$' > "$E/pkg"
plist=$(one '-org\.nix-community\.home\.claude-cache-proxy\.plist$')
service=$(plutil -extract ProgramArguments.2 raw -o - "$plist")
printf '%s\n' "$service" | sed -nE 's|^/bin/wait4path /nix/store && exec (/nix/store/[^ ]+-agent-tools-cache-proxy) --port 27183 --keepalive --reorder$|\1|p' > "$E/launcher"
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
```

- [ ] **Step 3: Write the run and measurement script `$E/ac3.py` (scratch, never committed)**

Run it as `env PYTHONPATH="$PWD/python" python3 $E/ac3.py run <on|off> <E> <port>` and `… measure <on|off> <E> <proxy log>`. `$E` holds no other `.py` file.

- **`run`** (bound 11 min): it draws the nonce `N`, creates the worktree `$S/i429/ac3-<arm>-<N>` (root rule), and runs `["claude", "-p", "--model", "sonnet", "--output-format", "json", <parent prompt with N>]` with that `cwd`. The environment is `os.environ` minus `PYTHONPATH`, plus `PATH=<pkg>/bin:<PATH>`, the four root overrides with `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`, and `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`, set explicitly because a nested `-p` writes no transcript without it (D23). The child gets `start_new_session=True`, and its process group is killed at 600 s. It records `start` and `end` (UTC, `%Y-%m-%dT%H:%M:%S.%fZ` to ms), the exit code, stdout to `<E>/<arm>.json` and stderr to `<E>/<arm>.err`. From stdout's `session_id` it finds every `$HOME/.claude-accounts/profiles/p2/projects/*/<session_id>.jsonl` (exactly one) and every sibling `<session_id>/` directory, and copies them into `<E>/<arm>-projects/<project dir name>/`. Last, it removes the worktree with `git worktree remove --force`.
- **`measure`**: over `transcript_jobs(<E>/<arm>-projects, None)` the subagents are the non-root jobs, each typed by its `.meta.json` `agentType`, with its first and last record `timestamp`. Siblings 1 and 2 are the two `general-purpose` transcripts by first timestamp. The window is `since` = sibling 2's first timestamp and `before` = run `end` + 1 s. Each sibling's `startup` is `scan_transcript((path, False), since=parse_rfc3339_utc(since), before=parse_rfc3339_utc(before), threshold=agent_cache_report.DEFAULT_CONTEXT_THRESHOLD)["startup"]`. The proxy counts are lines containing `"path":"/v1/messages`, `"reorder":"applied"` and `"reorder"`, and the `ping` lines with their `usage`. It writes `<E>/<arm>.summary.json` with the session id, `subtype`, `is_error`, `total_cost_usd`, window, both siblings' timestamps and `startup`, the counts and `void` (a list of reasons).
- A run is void when `subtype` is not `success` or `is_error` is true; the subagents are not exactly two, both `general-purpose`; sibling 2's first timestamp precedes sibling 1's last; sibling 2's windowed `startup` is `None` or sibling 1's is not `None`; the log has no `/v1/messages` line; or the arm check of the Invariants fails.

- [ ] **Step 4: The on arm**

Start the proxy with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh $E/run-proxy.sh $E/proxy-on.log $E/proxy.pid "$(cat $E/ca)" "$(cat $E/launcher)" --keepalive --reorder`. Run one bounded `sleep 3`, then (timeout 30 s) read `port` from the log's first line, which must be a `listening` line with `"keepalive":true` and `"reorder":true` and a port other than 27183, 8160, 4322, 27450 and 27451 (else stop it and report BLOCKED with the line). `curl -q --noproxy '*' -fsS --max-time 2 --retry 5 --retry-connrefused http://127.0.0.1:<port>/_proxy/health` must print `{"service":"cache-proxy","status":"ok"}`.

Run (timeout 720 s): `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 $E/ac3.py run on $E <port>`, then `env PYTHONPATH="$PWD/python" python3 $E/ac3.py measure on $E $E/proxy-on.log`. Stop the proxy (`kill "$(cat $E/proxy.pid)"`) and check that its health probe no longer answers. A usage-limit refusal (a `429` in the log or the child's output) stops the task: report BLOCKED `blocked_on=usage_limit`, with nothing committed.

- [ ] **Step 5: The off arm**

Repeat Step 4 with `$E/proxy-off.log`, the flags `--keepalive` alone (the `listening` line has no `reorder`), and the arm `off`. A void arm is rerun once, with a new worktree and nonce, when the cutoff allows; both attempts are recorded. A second void stops the task as BLOCKED, with the void reasons.

- [ ] **Step 6: Read the runs through `agent-costs`**

```bash
for arm in on off; do
  [ -e "$E/$arm.summary.json" ] || continue
  read -r since before < <(jq -r '.window | "\(.since) \(.before)"' "$E/$arm.summary.json")
  just agent-costs --report cache --projects-dir "$E/$arm-projects" --events-since "$since" --events-before "$before" > "$E/$arm-report.txt"
  sed -n '/^Subagent start-up/,/^NOTE:/p' "$E/$arm-report.txt" > "$E/$arm-startup.txt"
  grep -E '^ *general-purpose ' "$E/$arm-startup.txt"
done
```

Each table's `general-purpose` row shows `subagents` `1`, with a `1st read` that matches `summary.json`'s sibling-2 `startup.read` within the table's `k` rounding. Thresholds (AC3, D22), on the exact values: on `read` ≥ 10,000, and on `read` − off `read` ≥ 4,000.

- [ ] **Step 7: Record**

Append to `docs/spikes/cache-proxy-prefix-retest.md`, after one blank line, a section `## AC3 evidence — shared prefix` holding: the sentence `Appended by Task 4; the sections above are unchanged (D10).`; one table `| Arm | Session | Window | Sibling 2 1st read | Sibling 2 1st write | Threshold | Met |` with rows on, off and the difference (a skipped arm's row reads `not run: attempt deadline cutoff (human-pending)`); each run's start-up table from `$E/<arm>-startup.txt` in a fenced `text` block; and the conditions: host, `CODE_HEAD`, account `p2`, the wrapper and launcher paths with flags, each instance's port, the proxy counts and pings, both commands, and any rerun. If the report would pass 65,536 bytes, the fenced blocks go unchanged to the usage file under `## AC3 start-up tables`, linked from the section (D25).

Fill row `AC3`: `Observed` `sibling 2 1st read <on> on (≥ 10,000: met|missed), <off> off; on − off <d> (≥ 4,000: met|missed)`, with a skipped arm's half as in Step 1; `Commit` `CODE_HEAD`'s short SHA; `Conditions` host `mbp`, account `p2`, wrapper and launcher paths, `--model sonnet`, both windows, both session ids and `total_cost_usd`, `one trial per arm, not tuned (#422 D27)`. `Verdict` stays `—`. When a threshold is missed, report DONE_WITH_CONCERNS naming the value and its threshold.

- [ ] **Step 8: Verify**

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-prefix-retest.md
a=.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
test "$(grep -cx '## AC3 evidence — shared prefix' "$f")" -eq 1
if grep -q 'pending (Task 4)' "$a"; then exit 1; fi
grep -Eq '^\| AC3 \|.*(sibling 2 1st read|not run: attempt deadline cutoff)' "$a"
test "$(grep -Ec '^Attempt 2 (billing suffix|gain|verdict): ' "$f")" -eq 3
for p in "$f" docs/spikes/cache-proxy-prefix-retest-2-*.md; do test "$(wc -c < "$p")" -le 65536; done
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a" docs/spikes/cache-proxy-prefix-retest-2-*.md; then exit 1; fi
git diff --quiet "$CODE_HEAD" -- home lib justfile python tests flake.lock
test -z "$(git diff --name-only "$CODE_HEAD" | grep -v -e '^docs/spikes/cache-proxy-prefix-retest\.md$' -e '^docs/spikes/cache-proxy-prefix-retest-2-usage\.md$' -e '^\.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix\.acceptance\.md$' || true)"
echo ac3-recorded
```

Expected: `ac3-recorded`. At the starting commit it fails at the first `test`, because there is no AC3 section.

- [ ] **Step 9: Commit**

```bash
git add docs/spikes/cache-proxy-prefix-retest.md docs/spikes/cache-proxy-prefix-retest-2-usage.md .agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
launch-commit … -- -m "docs(spike): AC3 shared-prefix evidence, reorder on and off (issue 429)" -m "<session trailers>"
```

Before reporting, check that every instance this task started is gone and that `test "$(git worktree list | grep -c /i429/ || true)" = 0` passes.
