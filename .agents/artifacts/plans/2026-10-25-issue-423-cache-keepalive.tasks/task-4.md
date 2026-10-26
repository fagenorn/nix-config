# Task 4: AC2 evidence — the eight-minute parent wait, off then on

Spec § Live evidence (venue, AC2, conditions), per D13, D14 and D26, under #422 D14, D20, D24 and D27. On mbp, the built (never activated) `cache-proxy` launcher runs in the foreground on a free loopback port, first without `--keepalive` and then with it. Each arm is one fresh `claude -p` session, started through the built `claude` wrapper with a caller-set `ANTHROPIC_BASE_URL`. In it, subagent P reads six nonce files, dispatches child C in the foreground, and waits while C runs one foreground `sleep 480`. P's first call after C returns is measured from an isolated copy of the session's transcripts. This task changes no code. A missed threshold is recorded as observed, never tuned or rerun.

**Files:**
- Create: `docs/spikes/cache-proxy-keepalive.md`
- Create: `.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md`
- Scratch only: `$S/i423/ac2/` (the scripts, proxy logs, run output and transcript copies)

**Interfaces:**
- Consumes (Task 3, through `./result` after `just build`): the mbp launchd agent's `ProgramArguments`, `[<launcher>, "--port", "27183", "--keepalive"]`, and its `EnvironmentVariables.SSL_CERT_FILE`, read with `nix eval`; and `<hash>-claude-code-with-accounts-<version>/bin/claude` in the closure of `./result`. Also the `listening`, `request` and `ping` lines (Tasks 2–3), and `agent_tools.cache_keepalive.conversation_handle(session, agent)`.
- Consumes: `agent_tools.agent_cache_report.transcript_jobs(root, None)`, which returns `(path, is_root)` pairs, and `agent_cache_report._read_records(handle)`, whose first item is the transcript's calls as the cache report groups them. Each call has `tool_names` (a dict of id to name), `start` and `end` (datetimes), `start_raw`, `usage` and `context`. The script uses this private helper read-only, so that "call" means what the cache report means by it. Also the controller's `deadline_at`.
- Produces: the report, with its header lines and the section `## AC2 — keepalive works`; and the acceptance record, with rows `AC1`–`AC3`, `AC3` reading `pending (Task 5)`. Task 5 fills `AC3`.

**Invariants:**
- No `just switch`, `launchctl` or `systemctl`. Each proxy is a process this task started, on the port its own `listening` line names, and it is stopped before the next arm starts and before the task reports.
- The arms run off, then on. They differ only in `--keepalive`, and each uses a new scratch directory and nonce under one account.
- One trial per arm. An arm is **void** only for these reasons: `run_failed` (exit not 0, `subtype` not `success`, or `is_error`), `transcript_missing`, `subagents_not_two`, `parent_not_found` (not exactly one subagent transcript has an `Agent` or `Task` call), `no_measured_call`, `short_wait` (gap under 480 s), `small_own_share` (P's own share under 0.60), `no_messages_lines` (no `request` line for a path starting `/v1/messages`), `keepalive_field_mismatch` (on: such a line without `keepalive`; off: any line with it), and `handle_not_in_log` (on: no `request` line's `conversation` is P's handle). A void arm reruns once with a new nonce if the cutoff allows. A missed threshold is never void and never rerun (D26, #422 D27).
- The report holds numbers, ids, store paths and commands only, never transcript or prompt content beyond the prompt below. It stays at or under 65,536 bytes.

- [ ] **Step 1: Check the starting state**

Run (timeout 30 s), from the worktree root:

```bash
set -e
test "$(hostname -s)" = mbp
test -z "$(git status --short)"
grep -q '"--keepalive"' home/common/claude-code/default.nix
test ! -e docs/spikes/cache-proxy-keepalive.md
test ! -e .agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md
git rev-parse HEAD
```

Record `CODE_HEAD` (the printed SHA) and `ACCOUNT="$(claude-account active)"`.

**Deadline cutoff (D26).** Before each arm and before any rerun, compute the minutes left (root § Deadline). An arm runs only with at least 15 left. A skipped arm is not run, and the report and row `AC2` record it as `not run: attempt deadline cutoff`, with its exact Step 4 or 5 commands in `Conditions`. Steps 6 and 7 then cover only the arms that ran.

**Long runs.** Each `ac2.py run` takes about 10 minutes, above the Bash tool's 10-minute limit. Start it with `run_in_background: true` under `launch-scope exec`, and wait for its completion notification in the same turn. Never poll it in a loop.

- [ ] **Step 2: Build and locate the built outputs**

Run (timeout 3600 s): `just build`. Then (timeout 300 s):

```bash
set -euo pipefail
E=$S/i423/ac2; mkdir -p "$E"
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

`$E/ac2.py`, run as `PYTHONPATH="$PWD/python" python3 $E/ac2.py <subcommand> …`. `$E` holds no other `.py` file.

- **`run <arm> <E> <account> <port>`** (it kills the child's process group at 1,200 s):
  - It makes `N = secrets.token_hex(4)` and the directory `<E>/run-<arm>-<N>`. There it writes `part-1.txt` … `part-6.txt`, each 500 lines of exactly 96 bytes, so 48,000 bytes per file. Line `i` of part `k` is `f"I423-{arm}-{N} part {k} line {i:03d}:"`, then words drawn by `random.Random(f"{N}:{k}:{i}")` from `cache entry parent child proxy minute token prefix session agent request reply stream window budget ledger branch commit review plan task spec issue build test shell file line read write wait sleep`, while they fit, then padded with spaces to 95 characters and a `\n`.
  - It runs `[<pkg>/bin/claude, "-p", PROMPT, "--model", "sonnet", "--dangerously-skip-permissions", "--output-format", "json"]` with `cwd` set to that directory and `start_new_session=True`. The environment is `os.environ` minus `ANTHROPIC_BASE_URL` and `ENABLE_TOOL_SEARCH`, plus `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`, `ENABLE_TOOL_SEARCH=true`, `CLAUDE_ACCOUNT=<account>`, `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`, `BASH_DEFAULT_TIMEOUT_MS=600000` and `BASH_MAX_TIMEOUT_MS=600000` (so that C's `sleep 480` runs to its end even if the model omits the timeout), and `PATH=<pkg>/bin:$PATH` (D13, D26). `PROMPT` is exactly:

    `I423-MAIN-<N>. Use the Agent tool exactly once, in the foreground, with subagent_type general-purpose, description "parent P" and this prompt: "I423-P-<N>. First read each of the files part-1.txt to part-6.txt in the current directory with the Read tool, one Read call per file. Then use the Agent tool exactly once, in the foreground and never in the background, with subagent_type general-purpose, description "child C" and this prompt: 'I423-C-<N>. Run exactly one Bash command, sleep 480, in the foreground, with the Bash tool's timeout set to 600000 and run_in_background false. When it finishes, reply with exactly: slept'. When the child answers, reply with exactly: P done". When it answers, reply with exactly: done`
  - It writes stdout to `<E>/<arm>.json`, stderr to `<E>/<arm>.err`, and `<E>/<arm>.run.json` with the nonce, `start` and `end` (UTC, `%Y-%m-%dT%H:%M:%S.%fZ` cut to milliseconds) and the exit code.
  - From `session_id` it finds exactly one `<session_id>.jsonl` among `~/.claude/projects/*/` and `~/.claude-accounts/profiles/*/projects/*/`, after `os.path.realpath` removes duplicates. It copies that file and its sibling directory `<session_id>/` into `<E>/<arm>-projects/<project dir name>/`, then removes the run directory.
- **`measure <arm> <E> <proxy log>`** writes `<E>/<arm>.summary.json`:
  - Over `transcript_jobs(<E>/<arm>-projects, None)`, it reads each subagent (non-root) transcript's calls with `_read_records`. A *dispatch* call is one whose `tool_names` values include `Agent` or `Task`. P is the one subagent transcript with a dispatch call, and C is the other.
  - The predecessor is P's last dispatch call, and the measured call is the call after it. It records `gap_s = (measured.start - predecessor.end).total_seconds()`, `ratio = measured.usage["cache_creation_input_tokens"] / predecessor.context` and `own_share = 1 - calls[0].context / predecessor.context`, with both calls' `start_raw`, `context` and `usage`.
  - The window is `since = measured.start_raw` and `before = measured.start + 1 s`, in the same format.
  - P's handle is `conversation_handle(sessionId, agentId)`, from the first record of P's transcript that carries both. `sessionId` must equal the run's `session_id`; otherwise the arm is void with `transcript_missing`.
  - From the proxy log (one JSON object per line) it takes the `request` lines whose `path` starts with `/v1/messages`, the count of those that carry `keepalive`, the count of all lines that carry `keepalive`, whether any request line's `conversation` equals P's handle, and P's `ping` lines with their `status`, `outcome` and `usage.cache_read_input_tokens`.
  - It records `session_id`, `subtype`, `is_error`, `total_cost_usd`, P's handle, the void reasons (Invariants) and the run metadata.

- [ ] **Step 4: The off arm**

Start the proxy with the Bash tool's `run_in_background: true`: `launch-scope exec … -- sh $E/run-proxy.sh $E/proxy-off.log $E/proxy-off.pid "$(cat $E/ca)" "$(cat $E/launcher)"`. In the next call (timeout 30 s): `PORT=$(head -1 $E/proxy-off.log | jq -er 'select(.event == "listening" and (has("keepalive") | not)) | .port') && curl -q --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:$PORT/_proxy/health"`. It must print `{"service":"cache-proxy","status":"ok"}`. If the log is still empty, make one bounded wait of at most 5 s and check once more; a second miss is BLOCKED with the log's content.

Run `ac2.py run off $E "$ACCOUNT" "$PORT"` (Long runs), then `ac2.py measure off $E $E/proxy-off.log` (timeout 120 s). Stop the proxy with `kill "$(cat $E/proxy-off.pid)"` and check that the health probe no longer answers.

- [ ] **Step 5: The on arm**

Repeat Step 4 with `proxy-on.log`, `proxy-on.pid`, the extra launcher argument `--keepalive`, a `listening` line that must have `"keepalive":true`, and the arm `on`.

A void arm is rerun once, in a new directory with a new nonce, if the cutoff allows. Both attempts are recorded. A second void leaves the arm void.

- [ ] **Step 6: Read each valid arm through the cache report**

```bash
for arm in off on; do
  s=$E/$arm.summary.json; [ -e "$s" ] && [ "$(jq '.void | length' "$s")" -eq 0 ] || continue
  just agent-costs --report cache --projects-dir "$E/$arm-projects" \
    --events-since "$(jq -r .window.since "$s")" --events-before "$(jq -r .window.before "$s")" > "$E/$arm-report.txt"
  grep -E '^Subagent deaths ' "$E/$arm-report.txt"
done
```

Thresholds (AC2):
- off: `ratio > 0.50`, the line `Subagent deaths 1 …`, and a death-table row naming `general-purpose` and `child dispatch`;
- on: `ratio < 0.10`, the line `Subagent deaths 0 …`, and at least one P `ping` line with a 2xx `status`, `outcome` `complete` and `cache_read_input_tokens > 0`.

- [ ] **Step 7: Record**

Create `docs/spikes/cache-proxy-keepalive.md`:

```markdown
# Cache proxy keepalive evidence — issue 423

Run: <date> on host mbp; Claude Code <version>; wrapper `<pkg>/bin/claude`; launcher `<launcher>`; account `<ACCOUNT>`; code `<CODE_HEAD short>`; model `sonnet`.

AC2: <met|missed|void|not run>
AC3: pending (Task 5)

## AC2 — keepalive works
```

`AC2` reads `met` when both arms are valid and meet every Step 6 threshold, `missed` when both are valid and one threshold fails, `void` when an arm ended void, and `not run` when the cutoff skipped an arm. The section holds one table, `| Arm | Session | P handle | Gap (s) | Predecessor context | Measured creation | Ratio | Own share | Subagent deaths in window | P pings (complete, max read) | Threshold | Met |`, with rows `off` and `on`. A skipped arm's row reads `not run: attempt deadline cutoff`, and a void arm's row gives its reasons. Below the table come each valid arm's `Subagent deaths` line and death table, copied from `$E/<arm>-report.txt` into a fenced `text` block; the proxy-log counts; both windows; both `total_cost_usd` values; the two run commands; any rerun; and the line `One trial per arm, not tuned (#422 D27).`

Create `.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md`, with the header `# Acceptance record — issue #423` and the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`. Each `Criterion` is the issue's line verbatim, without its checkbox. The rows are:
- `AC1`: kind `code`, check `just agent-workflow-tests` (`tests/test_cache_keepalive.py`), `Observed` `in final verification`, and `—` in the other columns.
- `AC2`: kind `evidence`, check the Step 4–6 commands. `Observed` is `ratio <on> on (< 0.10: met|missed), <off> off (> 0.50: met|missed); deaths in window <on> on, <off> off; P complete pings <n>, max read <r>`, or a skipped or void arm's text. `Commit` is `CODE_HEAD`'s short SHA. `Conditions`: host `mbp`, account, wrapper and launcher paths, `--model sonnet`, both session ids and windows, `one trial per arm, not tuned (#422 D27)`. `Verdict` is `—`, or `human-pending` when the cutoff skipped an arm.
- `AC3`: kind `evidence`, `Observed` `pending (Task 5)`, and `—` in the other columns.

When a threshold is missed or an arm ends void, report DONE_WITH_CONCERNS with the value and its threshold.

- [ ] **Step 8: Verify**

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-keepalive.md
a=.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md
test "$(grep -c '^## AC2 — keepalive works$' "$f")" -eq 1
grep -Eqx 'AC2: (met|missed|void|not run)' "$f"
grep -qx 'AC3: pending (Task 5)' "$f"
test "$(grep -c '^| AC[123] |' "$a")" -eq 3
grep -q '^| AC3 |.*pending (Task 5)' "$a"
if grep '^| AC2 |' "$a" | sed 's/human-pending//g' | grep 'pending' >/dev/null; then exit 1; fi
if grep -q '^| AC2 |.*not run: attempt deadline cutoff' "$a"; then grep -Eq '^\| AC2 \|.*\| human-pending \|$' "$a"; fi
test "$(wc -c < "$f")" -le 65536
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a"; then exit 1; fi
git diff --quiet "$CODE_HEAD" -- home lib justfile python tests
test -z "$(git status --porcelain | grep -v -e ' docs/spikes/cache-proxy-keepalive\.md$' -e ' \.agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive\.acceptance\.md$' || true)"
echo ac2-recorded
```

Expected: `ac2-recorded`. At the starting commit it fails at the first `test`, because the report does not exist.

- [ ] **Step 9: Commit**

```bash
git add docs/spikes/cache-proxy-keepalive.md .agents/artifacts/plans/2026-10-25-issue-423-cache-keepalive.acceptance.md
launch-commit … -- -m "docs(spike): AC2 keepalive evidence, the parent wait off and on (issue 423)" -m "<session trailers>"
```

Before reporting, check that no proxy this task started is alive (`kill -0 "$(cat $E/proxy-<arm>.pid)"` fails for each arm that ran) and that no `$E/run-*` directory remains.
