# Task 5: AC3 evidence — the A/B pipeline eval, on then off

Spec § Live evidence (AC3, conditions), per D13, D15, D21, D26 and D29, under #422 D14, D20, D24 and D27. On mbp, `just evals from-issue 1` runs once with the built `cache-proxy` launcher started with `--keepalive`, then once with it started without the flag. Each eval reaches its proxy through the built `claude` wrapper and a caller-set `ANTHROPIC_BASE_URL`. An arm's cost is its own transcripts' list price, plus, in the on arm, its pings priced from the proxy log. This task changes no code. The result is recorded as observed, never rerun (#422 D27).

**Files:**
- Modify: `docs/spikes/cache-proxy-keepalive.md` (the line `AC3: pending (Task 5)`, then append the section `## AC3 — no regression`; every other line stays as Task 4 committed it)
- Modify: `.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md` (row `AC3` only)
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (the eval runner appends one line per arm that ran)
- Scratch only: `$S/i423/ac3/` (the scripts, proxy logs, eval output and transcript copies)

**Interfaces:**
- Consumes (Task 3, through `./result` after `just build`): the mbp launchd agent's `ProgramArguments`, `[<launcher>, "--port", "27183", "--keepalive"]`, and its `EnvironmentVariables.SSL_CERT_FILE`, read with `nix eval`; and `<hash>-claude-code-with-accounts-<version>/bin/claude` in the closure of `./result`. Also the `listening`, `ping` and `keepalive_end` lines (Tasks 2–3).
- Consumes: `agent_tools.agent_costs.PRICING`, `model_family(model)` and `cache_write_split(usage) -> (cw_1h, cw_5m)`; `just agent-costs --format json --days 0 --projects-dir <dir>`, whose `.strata.claude` has `cost_basis` and `totals.cost_usd`; `run-eval.sh`'s `workdir: <path>` and `VERDICT: <v>` output lines and its appended `results.jsonl` line; Task 4's report header line `AC3: pending (Task 5)` and record row `AC3`; and the controller's `deadline_at`.
- Produces: row `AC3` filled, the report's `AC3:` line, its appended section, and the new `results.jsonl` lines.

**Invariants:**
- No `just switch`, `launchctl` or `systemctl`. Each proxy is a process this task started, on the port its own `listening` line names, and it is stopped before the next arm starts and before the task reports.
- The arms run on, then off. They differ only in `--keepalive`. Both use one account, `EVAL_TIMEOUT=900`, the default `EVAL_MODEL`, and the same environment otherwise (D15, D26).
- An arm's transcripts are exactly the sessions whose root transcript's `cwd` is that eval's sandbox repository or lies below it, each with every transcript of that session id in any project directory, copied into the arm's own directory (#429 D19, D29). A session that enters a worktree writes its subagents under the worktree's project directory, as `agent_costs.find_sessions` already handles.
- Pings are priced only through `agent_costs` (D15). The off arm's log must have no `ping` line.
- Report lines outside the `AC3:` line and the appended section, and acceptance rows other than `AC3`, are unchanged. The report stays at or under 65,536 bytes.

- [ ] **Step 1: Check the starting state**

Run (timeout 30 s), from the worktree root:

```bash
set -e
test "$(hostname -s)" = mbp
test -z "$(git status --short)"
grep -qx 'AC3: pending (Task 5)' docs/spikes/cache-proxy-keepalive.md
grep -q '^| AC3 |.*pending (Task 5)' .agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md
git rev-parse HEAD
wc -l < home/common/agent-skills/evals/results/results.jsonl
```

Record `CODE_HEAD` (the printed SHA), `RESULTS_BEFORE` (the line count) and `ACCOUNT="$(claude-account active)"`.

**Deadline cutoff (D26).** Before each arm, compute the minutes left (root § Deadline). An eval arm runs only with at least 20 left. A skipped arm is not run; the report and row `AC3` record it as `not run: attempt deadline cutoff`, with its exact Step 4 or 5 commands in `Conditions`, and its `Verdict` reads `human-pending`. Steps 6 and 7 then cover only the arms that ran.

**Long runs.** An eval arm takes about 5 minutes and is bounded by `EVAL_TIMEOUT=900`, above the Bash tool's 10-minute limit. Start it with `run_in_background: true` under `launch-scope exec`, and wait for its completion notification in the same turn. Never poll it in a loop.

- [ ] **Step 2: Build and locate the built outputs**

Run (timeout 3600 s): `just build`. Then (timeout 300 s):

```bash
set -euo pipefail
E=$S/i423/ac3; mkdir -p "$E"
set -- $(nix-store --query --requisites ./result | grep -- '-claude-code-with-accounts-[^/]*$' || true); test "$#" -eq 1; echo "$1" > "$E/pkg"
a='.#darwinConfigurations.mbp.config.home-manager.users.anis.launchd.agents.claude-cache-proxy.config'
nix eval --json "$a.ProgramArguments" > "$E/args.json"
jq -e '.[1:] == ["--port","27183","--keepalive"]' "$E/args.json"
jq -r '.[0]' "$E/args.json" > "$E/launcher"
nix eval --raw "$a.EnvironmentVariables.SSL_CERT_FILE" > "$E/ca"
nix-store --query --requisites ./result | grep -qxF "$(cat "$E/launcher")"
test -s "$(cat "$E/ca")"
"$(cat "$E/launcher")" --help | grep -q -- --keepalive
echo located
```

Expected: `true`, then `located`.

- [ ] **Step 3: Write the scratch scripts (never committed)**

`$E/run-proxy.sh`:

```sh
#!/bin/sh
# The built cache-proxy launcher in the foreground on a free loopback port (D13, D26).
# run-proxy.sh <log> <pidfile> <ca bundle> <launcher> [--keepalive]
log=$1 pidfile=$2 ca=$3 launcher=$4; shift 4
echo $$ > "$pidfile"
exec env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin SSL_CERT_FILE="$ca" "$launcher" --port 0 "$@" >>"$log" 2>&1
```

`$E/ac3.py`, run as `PYTHONPATH="$PWD/python" python3 $E/ac3.py <subcommand> …`. `$E` holds no other `.py` file.
- **`collect <arm> <E> <repo> <since-epoch>`** considers every root transcript `<dir>/<sid>.jsonl` among `~/.claude/projects/*/` and `~/.claude-accounts/profiles/*/projects/*/`, after `os.path.realpath` removes duplicates, whose mtime is at or after `<since-epoch>`. It keeps those whose first record carrying `cwd` has `cwd == <repo>` or a `cwd` starting with `<repo>/`. Then, for each kept session id `<sid>`, it copies every `<d>/<sid>.jsonl` and every `<d>/<sid>/` directory in any project directory `<d>` under those same roots, the root transcript's own included, into `<E>/<arm>-eval-projects/<basename of d>/`, so that `find_sessions`, which keys transcripts by session id across project directories, sees each session whole (D29). It prints the session ids, one per line. At least one is required.
- **`pings <log>`** prints one JSON object from the proxy log. It holds `count` (the `ping` lines); `outcomes` (counts by `"<status> <outcome>"`); `cost_usd` (the sum, over the `ping` lines that have `usage`, of `(input * p_in + output * p_out + cw_1h * p_1h + cw_5m * p_5m + read * p_read) / 1e6`, with `p_* = PRICING[model_family(line["model"])]` and `cw_1h, cw_5m = cache_write_split(line["usage"])`); `end_reasons` (the `keepalive_end` lines, counted by `reason`); `messages_lines` (the `request` lines whose `path` starts with `/v1/messages`); `messages_with_keepalive` (those of them that carry `keepalive`); and `lines_with_keepalive` (every line that carries `keepalive`, the `listening` line included).

- [ ] **Step 4: The on arm**

Start the proxy with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh $E/run-proxy.sh $E/proxy-on.log $E/proxy-on.pid "$(cat $E/ca)" "$(cat $E/launcher)" --keepalive`. In the next call (timeout 30 s): `PORT=$(head -1 $E/proxy-on.log | jq -er 'select(.event == "listening" and .keepalive == true) | .port') && curl -q --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:$PORT/_proxy/health"`. It must print `{"service":"cache-proxy","status":"ok"}`. If the log is still empty, make one bounded wait of at most 5 s and check once more; a second miss is BLOCKED with the log's content.

Record `SINCE=$(date +%s)`, then run (Long runs): `env PATH="$(cat $E/pkg)/bin:$PATH" ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" ENABLE_TOOL_SEARCH=true CLAUDE_ACCOUNT="$ACCOUNT" EVAL_TIMEOUT=900 just evals from-issue 1 > $E/on-eval.txt 2>&1`.

Then (timeout 300 s): read `VERDICT:` and `workdir:` from `$E/on-eval.txt`, and check that `results.jsonl` gained exactly one line. Run `ac3.py collect on $E <workdir>/repo "$SINCE"`. Stop the proxy (`kill "$(cat $E/proxy-on.pid)"`) and check that the health probe no longer answers.

- [ ] **Step 5: The off arm**

Repeat Step 4 with `proxy-off.log`, `proxy-off.pid`, no `--keepalive`, a `listening` line that has no `keepalive` key, the output `$E/off-eval.txt`, and the arm `off`.

- [ ] **Step 6: Cost each arm that ran**

```bash
for arm in on off; do
  [ -e "$E/$arm-eval.txt" ] || continue
  just agent-costs --format json --days 0 --projects-dir "$E/$arm-eval-projects" > "$E/$arm-costs.json"
  jq -e '.strata.claude.cost_basis == "list-price"' "$E/$arm-costs.json"
  jq '.strata.claude.totals.cost_usd' "$E/$arm-costs.json"
  PYTHONPATH="$PWD/python" python3 "$E/ac3.py" pings "$E/proxy-$arm.log" > "$E/$arm-pings.json"
  cat "$E/$arm-pings.json"
done
[ ! -e "$E/on-pings.json" ] || jq -e '.messages_lines >= 1 and .messages_with_keepalive == .messages_lines' "$E/on-pings.json"
[ ! -e "$E/off-pings.json" ] || jq -e '.messages_lines >= 1 and .lines_with_keepalive == 0 and .count == 0' "$E/off-pings.json"
```

These are the venue checks (D13). A failed one is recorded in the report and the row, reported as DONE_WITH_CONCERNS, and never rerun. An arm's total is its transcripts' `cost_usd` plus its pings' `cost_usd`. Thresholds (AC3): the on run's `VERDICT:` line reads `PASS`, and the on total is lower than the off total.

- [ ] **Step 7: Record**

In `docs/spikes/cache-proxy-keepalive.md`, replace the line `AC3: pending (Task 5)` with `AC3: met`, `AC3: missed` (an arm ran and a threshold failed) or `AC3: not run` (the cutoff skipped an arm). Then append a section `## AC3 — no regression` holding:
- one table `| Arm | VERDICT | wall_s | Sessions | Transcript cost | Pings | Ping outcomes | Ping cost | keepalive_end reasons | Total |`, with rows `on` and `off` (a skipped arm's row reads `not run: attempt deadline cutoff`);
- both appended `results.jsonl` lines, cited by their `ts`, `verdict`, `wall_s` and `workdir`;
- the conditions: host, `CODE_HEAD`, account, the wrapper and launcher paths, `EVAL_TIMEOUT=900`, the eval model, both commands, and the line `One trial per arm, never rerun (#422 D27).`;
- per D21, one sentence noting that `from-issue 1` runs take about 4–6 minutes, so few conversations reach a due time, and that run-to-run variance can exceed the pings' effect.

Fill row `AC3`:
- `Observed`: `on VERDICT <v>, total $<on> (transcripts $<t>, <n> pings $<p>); off total $<off>; on < off: met|missed`, or with a skipped arm's half as in Step 1's cutoff.
- `Commit`: `CODE_HEAD`'s short SHA.
- `Conditions`: host `mbp`; account; wrapper and launcher paths; `EVAL_TIMEOUT=900`; both `results.jsonl` `ts` values; the ping outcomes and `keepalive_end` reasons; `one trial per arm, never rerun (#422 D27)`.
- `Verdict`: stays `—`, or reads `human-pending` under the cutoff.

When a threshold is missed, report DONE_WITH_CONCERNS with both totals and the on `VERDICT`.

- [ ] **Step 8: Verify**

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-keepalive.md
a=.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md
r=home/common/agent-skills/evals/results/results.jsonl
test "$(grep -c '^## AC3 — no regression$' "$f")" -eq 1
grep -Eqx 'AC3: (met|missed|not run)' "$f"
if grep -q 'pending (Task 5)' "$f" "$a"; then exit 1; fi
grep -Eq '^\| AC3 \|.*(VERDICT|not run: attempt deadline cutoff)' "$a"
added=$(( $(wc -l < "$r") - RESULTS_BEFORE )); test "$added" -ge 0; test "$added" -le 2
test "$(git diff "$CODE_HEAD" -- "$r" | grep -c '^+{' || true)" -eq "$added"
test "$(wc -c < "$f")" -le 65536
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a"; then exit 1; fi
git diff --quiet "$CODE_HEAD" -- home/common/claude-code lib justfile python tests
test -z "$(git status --porcelain | grep -v -e ' docs/spikes/cache-proxy-keepalive\.md$' -e ' \.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive\.acceptance\.md$' -e ' home/common/agent-skills/evals/results/results\.jsonl$' || true)"
echo ac3-recorded
```

Expected: `ac3-recorded`. At the starting commit it fails at the first `test`, because the report has no AC3 section.

- [ ] **Step 9: Commit**

```bash
git add docs/spikes/cache-proxy-keepalive.md .agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md home/common/agent-skills/evals/results/results.jsonl
launch-commit … -- -m "docs(spike): AC3 keepalive evidence, the A/B pipeline eval (issue 423)" -m "<session trailers>"
```

Before reporting, check that no proxy this task started is alive (`kill -0 "$(cat $E/proxy-<arm>.pid)"` fails for each arm that ran).
