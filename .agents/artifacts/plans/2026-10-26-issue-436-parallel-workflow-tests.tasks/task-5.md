# Task 5: Concurrency audit, serial-mode evidence and the acceptance record

Spec § Concurrency hazards (D7), § Default cap and AC5 (D10) and § Test seams (AC4, AC5). Three full parallel runs and one serial run of `just agent-workflow-tests`, at the code head Tasks 1–4 produced:
- run 1 at the default cap;
- run 2 at `--jobs 16`;
- run 3 at the default cap again;
- one serial run, `--jobs 1`.

After each parallel run, check that the run left no shared residue. Then record the evidence in the acceptance record. At design time no hazard was found at caps 4, 8 and 32. A planning run of this plan's runner over all 104 members passed at cap 4 in 399 s on eleven-m5. This task therefore expects to change no code. A hazard that does surface is fixed here, by D7's rule.

**Files:**
- Create: `.agents/artifacts/plans/2026-10-26-issue-436-parallel-workflow-tests.acceptance.md`
- Modify (only when a run surfaces a hazard): the suite test module the hazard names, nothing else

**Interfaces:**
- Consumes: Tasks 1–4 at `HEAD`, and `just agent-workflow-tests [--jobs N]`, whose last stdout line is `suite-runner: summary members=<n> passed=<p> failed=<f> jobs=<N> wall=<s>s`.
- Produces: the acceptance record, with rows `AC1`–`AC5` in order. `AC4` and `AC5` carry their evidence, and the sdd controller writes every `Verdict`.

**Invariants:**
- Before the first run, `git status --short` prints nothing. `CODE_HEAD` is `git rev-parse HEAD` at that moment, and every run is taken at `CODE_HEAD`.
- Each run goes in the foreground under `launch-scope exec`, with timeout 3600 s, from the worktree root. Its output goes to a log under the scratch root, never into the worktree. Logs are not committed.
- A parallel run passes the audit only when all of these hold:
  - it exits 0, and its summary line says `members=104` and `failed=0`;
  - `git status --porcelain --ignored` gains no entry other than `__pycache__/` directories;
  - no new path in the real home's `.agents`, `.claude`, `.codex`, `.config` or `.cache`, or in the system temp directory, is a hazard (see Step 2).
- The serial run must exit 0, with `members=104`, `failed=0` and `jobs=1` in its summary.
- A hazard is fixed only by giving the test its own temporary location for the path, home or fixture directory it shares. Never add a serial-exemption list, a retry, a sleep or a cross-process lock (D7). If the shared state is not a test's own (production code writing a fixed path), stop as BLOCKED with the evidence.

- [ ] **Step 1: Record the starting point**

```bash
S=$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)
A="$S/i436-audit"; mkdir -p "$A"
test -z "$(git status --short)" && git rev-parse HEAD > "$A/code-head" && hostname -s > "$A/host" && python3 --version > "$A/python"
```

The later steps use `S` and `A`. Run every step in one shell, or set both again first.

- [ ] **Step 2: Three audited parallel runs**

For `N` in `1 2 3`, with `ARGS` empty for runs 1 and 3 and `--jobs 16` for run 2:

```bash
git status --porcelain --ignored | sort > "$A/run-$N.git-before"
touch "$A/run-$N.marker"
launch-scope exec … -- bash -c "just agent-workflow-tests $ARGS < /dev/null > '$A/run-$N.log' 2>&1; echo \$? > '$A/run-$N.exit'"
git status --porcelain --ignored | sort > "$A/run-$N.git-after"
comm -13 "$A/run-$N.git-before" "$A/run-$N.git-after" | grep -v '__pycache__/$' > "$A/run-$N.git-new" || true
find "$HOME/.agents" "$HOME/.claude" "$HOME/.codex" "$HOME/.config" "$HOME/.cache" -newer "$A/run-$N.marker" 2>/dev/null > "$A/run-$N.home-new" || true
find "${TMPDIR:-/tmp}" /tmp/ -mindepth 1 -maxdepth 1 -newer "$A/run-$N.marker" 2>/dev/null > "$A/run-$N.tmp-new" || true
tail -1 "$A/run-$N.log"; cat "$A/run-$N.exit"; wc -l < "$A/run-$N.git-new"
```

Expected per run: a `summary members=104 passed=104 failed=0 jobs=<4|16> …` line, exit `0`, and `0` new git entries.

Classify each path in `run-$N.home-new` and `run-$N.tmp-new`. This is a shared host, and live agent sessions (this one included) write there throughout a run. **Session noise** is one of:
- the session and history stores of Claude Code (`~/.claude/projects`, `sessions`, `session-env`, `shell-snapshots`, `file-history`, `tasks`, `todos`, `jobs`, `teams`, `paste-cache`, `daemon*`, `history.jsonl`, `backups`, `cache`, `plugins`, `feedback`, and its settings-sync and policy files);
- Codex's (`~/.codex/sessions`, `.tmp`, `cache`, `*.sqlite*`, `history.jsonl`, `session_index.jsonl`, `thread-writer-locks`, `app-server-*`);
- the hook state under `~/.agents/state/context-meter` and `~/.agents/state/guard`, and `~/.cache/nix`;
- a temp entry whose name carries a random component (a `mkdtemp`/`mktemp` suffix, a `launch-scope-*` root).

Any other path is a **hazard candidate**. Search the suite for its name with `rg -l -F -- '<basename>' tests home/common/agent-skills/tests home/common/agent-skills/evals/tests`. A candidate the suite names is a **hazard**. A candidate no test names is noise from a concurrent session; record it with its likely writer. Then compare the temp lists of runs 1 and 3: a name that appears in both is a fixed name, which is a hazard candidate even if it looked random.

**When a run fails or finds a hazard**, run the failing module (or the module that names the hazard) alone, with the focused form from the Global Constraints:
- If it fails alone too, it is not a concurrency hazard. Apply the Global Constraints' known-flake rule if it is that assertion. Otherwise stop as BLOCKED with its failing lines (making slow or broken modules right is out of scope).
- If it passes alone, it is a D7 hazard. Find the shared path, home or fixture directory, give the test its own temporary location, and commit that fix on its own:

  ```bash
  launch-commit … -- -m "test(issue-436): <module> uses its own <path|home|fixture> under parallel runs" -m "<session trailers>"
  ```

  Then restart this task from Step 1.

- [ ] **Step 3: The serial run**

```bash
launch-scope exec … -- bash -c "just agent-workflow-tests --jobs 1 < /dev/null > '$A/serial.log' 2>&1; echo \$? > '$A/serial.exit'"
tail -1 "$A/serial.log"; cat "$A/serial.exit"
```

Expected: `suite-runner: summary members=104 passed=104 failed=0 jobs=1 wall=<s>s` and `0`. Expect roughly 25–30 minutes. A failure here is handled like a failed parallel run in Step 2.

- [ ] **Step 4: Write the acceptance record**

Create `.agents/artifacts/plans/2026-10-26-issue-436-parallel-workflow-tests.acceptance.md`, holding in order:
1. The heading `# Acceptance record — issue 436`.
2. The sentence `Taken on host <host>; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/436).`
3. One table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict`, and rows `AC1` to `AC5` in order:
   - `Criterion`: the issue's criterion line verbatim, without its `- [ ] ` checkbox (`gh issue view 436 --repo fagenorn/nix-config --json body --jq .body`), with each `|` escaped as `\|`.
   - `Kind` and `Check or command`: copied from the plan root's Acceptance map.
   - `AC1`–`AC3`: `Observed` is `in final verification`; `Commit` and `Conditions` are `—`.
   - `AC4`: `Observed` holds the serial run's summary line, then `parallel audit:` followed by the three runs' summary lines, then `residue: no hazard (D7)` (or the hazard fix commits), then `CI: the advisory job on the PR and the merge push, cited by ship with each run's AGENT_WORKFLOW_OBSERVATION_V1 record showing raw.suite "success" and its suite-runner summary line showing failed=0 (the suite step is continue-on-error, so a green job alone proves nothing; D15)`. `Commit` is `CODE_HEAD`'s short SHA. `Conditions` names the host, the `python3 --version` output, the four commands, `< /dev/null`, and the fact that each ran in the foreground under `launch-scope exec`.
   - `AC5`: `Observed` is `not measured — read by ship from the merge commit's push run (D10)`. `Commit` is `—`. `Conditions` is `hosted ubuntu-24.04, default cap 4, step "Run agent workflow tests" of job "Agent Workflow Tests (advisory)", threshold ≤ 360 s; the PR's CI run is the pre-merge reading cited in the PR; a reading over 360 s is returned to the caller, never answered by raising the default (D10)`.
   - `Verdict`: `—` in every row.
4. A section `## Concurrency audit (D7)` holding:
   - a table with the columns `Run | Command | Exit | Summary | New git entries | Hazards`, one row per run (the three parallel runs and the serial one, which has `—` in the last two columns);
   - one line per run that counts its session-noise paths, naming each hazard candidate a concurrent session wrote;
   - `### Timing report (run 1, default cap)`, holding run 1's lines from `suite-runner: timings, slowest first` through its summary line in one fenced `text` block.

- [ ] **Step 5: Verify**

```bash
set -e
f=.agents/artifacts/plans/2026-10-26-issue-436-parallel-workflow-tests.acceptance.md
test "$(grep -c '^| AC[1-5] |' "$f")" = 5
grep -q '^| AC4 |.*members=104 passed=104 failed=0 jobs=1 ' "$f"
grep -q '^| AC5 |.*not measured' "$f"
grep -q '^## Concurrency audit (D7)$' "$f"
grep -q '^### Timing report (run 1, default cap)$' "$f"
for n in 1 2 3; do test "$(cat "$A/run-$n.exit")" = 0; test ! -s "$A/run-$n.git-new"; done
test "$(cat "$A/serial.exit")" = 0
```

Expected: every command exits 0.

- [ ] **Step 6: Commit**

```bash
git add .agents/artifacts/plans/2026-10-26-issue-436-parallel-workflow-tests.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, concurrency audit and serial run (issue 436)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing. Unless Step 2 committed a hazard fix, `git diff --stat "$(cat "$A/code-head")"..HEAD -- python tests home justfile .github` also prints nothing.
