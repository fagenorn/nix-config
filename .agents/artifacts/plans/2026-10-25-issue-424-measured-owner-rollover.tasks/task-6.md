# Task 6: Evidence on mbp and the acceptance record

Spec test seam 6; per D12, D13 and D16. Build the final code head, prove the live rewrite with a one-prompt probe, run `just evals from-issue 1` in tree mode with the built settings, audit its transcripts, and record AC5 and AC6. This task changes no code: a value outside its bound is recorded as observed, never tuned toward the target. Never run `just switch`.

**Files:**
- Create: `.agents/artifacts/plans/2026-10-25-issue-424-measured-owner-rollover.acceptance.md`
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (the runner appends one row; commit it as written)

**Interfaces:**
- Consumes: Task 1's `MEASURED_NOTE` text (the audit matches `carries --context-tokens <n>, measured`); Task 4's built settings (the meter registered); Task 5's runner (sessions kept); `agent-costs --report cache --projects-dir … --days 0` (its reread table: `agent type  transcripts  reread above  peak p50  peak p90  peak max`, the main session's row named `main`).
- Produces: the acceptance record with rows `AC1`–`AC7`, `AC5` and `AC6` filled; the sdd controller writes every `Verdict`.

**Invariants:**
- Host `mbp` (`hostname -s`); `claude --version` reports `2.1.302`; the worktree is clean (`git status --short` prints nothing) before the eval, so its row records `tree_dirty: false`.
- Owner transcripts are the sandbox's root session (its `/from-issue` invoker) and every transcript that made a `workflow-state progress` call. AC5 holds when every progress call is joined to a measured note (none unmeasured) and every owner transcript's peak is at most 125,000; eval 1 has no `--auto`, so it is ledger-free and may make no progress call: a zero count is written as `0 progress calls — first clause vacuous on eval 1 (D16)`, and the probe stands as the live rewrite evidence.
- Tree mode runs the deployed `workflow-state` (only command-table rows are shimmed): the record names it in `Conditions` (D16).

- [ ] **Step 1: Check the preconditions and build**

```bash
hostname -s                    # expect: mbp
claude --version               # expect: 2.1.302 (Claude Code)
git status --short             # expect: no output
git rev-parse HEAD             # keep as CODE_HEAD
```

A different host, version or a dirty tree stops the task as BLOCKED, naming which. Build (Global Constraints), then, with `SCRATCH` the path `launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>` prints:

```bash
SETTINGS=$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')
jq -e '[.hooks.PreToolUse[0].hooks[].command | endswith("-agent-tools-context-meter")] | any' "$SETTINGS"
```

Expected: one path in `SETTINGS`, then `true`.

- [ ] **Step 2: The live rewrite probe (foreground, timeout 600 s)**

```bash
mkdir -p "$SCRATCH/probe"
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash -c 'cd "$0" && CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 timeout 300 claude -p --model haiku \
    --setting-sources project,local --settings "$1" --dangerously-skip-permissions \
    --output-format json "Run this exact Bash command once, then reply with only its output: echo workflow-state progress --context-tokens 1" \
    >probe.json 2>probe.err; echo "exit $?"' "$SCRATCH/probe" "$SETTINGS"
PROBE=$(find ~/.claude/projects -maxdepth 2 -name "$(jq -r .session_id "$SCRATCH/probe/probe.json").jsonl")
grep -o 'workflow-state progress --context-tokens [0-9]*' "$PROBE" | sort -u
grep -c 'carries --context-tokens [0-9]*, measured' "$PROBE"
```

Expected: `exit 0`; `PROBE` names one file; the first grep shows the original `… --context-tokens 1` and the executed `… --context-tokens <n>` with `n` above 1; the count is at least 1. Anything else stops the task as BLOCKED with `tail -5 "$SCRATCH/probe/probe.err"`.

- [ ] **Step 3: Run the eval (foreground, timeout 3500 s)**

```bash
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash -c 'EVAL_TREE="$PWD" EVAL_SETTINGS="$0" just evals from-issue 1 >"$1/eval.out" 2>&1; echo "exit $? at $(date -u +%Y-%m-%dT%H:%M:%SZ)"' "$SETTINGS" "$SCRATCH"
grep -E '^(workdir|VERDICT|claude exited)' "$SCRATCH/eval.out"
```

Expected: a `workdir:` line, a `claude exited` line and one `VERDICT:` line. Then copy the sandbox's transcripts into an isolated projects root:

```bash
WORK=$(sed -n 's/^workdir: //p' "$SCRATCH/eval.out" | head -1)
FRAG=$(printf '%s' "$(basename "$WORK")" | tr -c 'A-Za-z0-9' '-')
mkdir -p "$SCRATCH/eval-projects"
for dir in ~/.claude/projects/*"$FRAG"*; do cp -Rp "$dir" "$SCRATCH/eval-projects/"; done
find "$SCRATCH/eval-projects" -name '*.jsonl' | wc -l
```

Expected: at least 1 transcript. None means the run kept no session (D13): BLOCKED, naming `FRAG`.

- [ ] **Step 4: Audit the transcripts and read the peak table**

Write this script to `$SCRATCH/audit.py` and run `python3 -I "$SCRATCH/audit.py" "$SCRATCH/eval-projects" >"$SCRATCH/ac5-audit.txt"`:

```python
import json, pathlib, re, sys

PROGRESS = re.compile(r"(?:^|[\s;&|(/])workflow-state\s+progress(?:\s|$)")
NOTE = re.compile(r"carries --context-tokens (\d+), measured")
FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
root = pathlib.Path(sys.argv[1])
calls = measured = 0
for path in sorted(root.rglob("*.jsonl")):
    subagent = path.parent.name == "subagents"
    uses, notes, peaks = {}, {}, {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message") if record.get("type") == "assistant" else None
        if isinstance(message, dict) and (subagent or record.get("isSidechain") is not True):
            usage = message.get("usage")
            if message.get("model") != "<synthetic>" and isinstance(usage, dict):
                peaks[message.get("id")] = sum(int(usage.get(k) or 0) for k in FIELDS)
            for block in message.get("content") or []:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == "Bash"
                        and PROGRESS.search(str((block.get("input") or {}).get("command", "")))):
                    uses[block["id"]] = True
        attachment = record.get("attachment") if record.get("type") == "attachment" else None
        if (isinstance(attachment, dict) and attachment.get("type") == "hook_additional_context"
                and attachment.get("hookName") == "PreToolUse:Bash"):
            notes[attachment.get("toolUseID")] = " ".join(map(str, attachment.get("content") or []))
    meta = path.with_suffix(".meta.json")
    kind = json.loads(meta.read_text())["agentType"] if meta.is_file() else (
        "unknown" if subagent else "main")
    owner = not subagent or bool(uses)
    print(f"{path.relative_to(root)}\t{kind}\towner={owner}\tpeak={max(peaks.values(), default=0)}"
          f"\tprogress_calls={len(uses)}")
    for use_id in uses:
        found = NOTE.search(notes.get(use_id, ""))
        calls += 1
        measured += bool(found)
        print(f"  {use_id}\t{'measured ' + found.group(1) if found else 'NOT MEASURED'}")
print(f"TOTAL progress_calls={calls} measured={measured}")
```

Then (timeout 600 s):

```bash
tail -1 "$SCRATCH/ac5-audit.txt"
grep 'owner=True' "$SCRATCH/ac5-audit.txt"
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash -c 'just agent-costs --report cache --projects-dir "$0" --days 0 >"$1/ac5-cache.txt" 2>"$1/ac5-cache.err"; echo "exit $?"' "$SCRATCH/eval-projects" "$SCRATCH"
grep -n -E '^(agent type|main |general-purpose )' "$SCRATCH/ac5-cache.txt"
```

Expected: the `TOTAL` line, the owner lines, `exit 0`, and the reread table's rows. AC5 is met when `measured` equals `progress_calls` and every owner line's `peak=` is at most 125000 (and the reread table's `peak max` agrees with the audit's owner peaks); otherwise it is unmet with the offending lines named.

- [ ] **Step 5: Write the acceptance record**

Create `.agents/artifacts/plans/2026-10-25-issue-424-measured-owner-rollover.acceptance.md` holding, in order:

1. The heading `# Acceptance record — issue #424`.
2. The sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/424).`
3. One table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and rows `AC1`–`AC7` in order: `Criterion` is the issue's line verbatim without its `- [ ] ` checkbox (`gh issue view 424 --repo fagenorn/nix-config --json body --jq .body`), with `|` escaped as `\|`; `Kind` and `Check or command` copied from the plan root's Acceptance map; `AC1`–`AC4` and `AC7` read `in final verification` with `Commit` and `Conditions` `—`. `AC5`'s `Observed` holds the audit's `TOTAL` line, each owner line, the reread table's `main` row (and any other owner type's row) verbatim in backticks, and `met`/`unmet` per Step 4 (with the vacuous wording of **Invariants** when the count is 0). `AC6`'s holds the `VERDICT:` line verbatim. `Commit` is `CODE_HEAD`'s short SHA for both. `Conditions` names host `mbp`, Claude Code `2.1.302`, `EVAL_TREE` and `EVAL_SETTINGS` (the store path), `EVAL_MODEL` default, the eval's finishing instant, the copied project folder names, the deployed `workflow-state` (D16), and no `just switch`. `Verdict` is `—` everywhere.
4. `## Live rewrite probe` with the Step 2 command and both grep outputs in one fenced `text` block.
5. `## AC5 audit` with `ac5-audit.txt` whole, and `## AC5 reread table` with `ac5-cache.txt` whole, each in one fenced `text` block.
6. `## AC6 eval output` with the last 40 lines of `eval.out` in one fenced `text` block.

When AC5 or AC6 is unmet, also report the task DONE_WITH_CONCERNS naming the value and its bound.

- [ ] **Step 6: Verify**

```bash
set -e
f=.agents/artifacts/plans/2026-10-25-issue-424-measured-owner-rollover.acceptance.md
test "$(grep -c '^| AC[1-7] |' "$f")" = 7
grep -q '^| AC5 |.*TOTAL progress_calls=' "$f"
grep -q '^| AC6 |.*VERDICT:' "$f"
for heading in '## Live rewrite probe' '## AC5 audit' '## AC5 reread table' '## AC6 eval output'; do grep -qx "$heading" "$f"; done
git diff --stat -- home/common/agent-skills/evals/results/results.jsonl
```

Expected: every command exits 0, and the diff shows one added line.

- [ ] **Step 7: Commit**

```bash
git add .agents/artifacts/plans/2026-10-25-issue-424-measured-owner-rollover.acceptance.md \
  home/common/agent-skills/evals/results/results.jsonl
launch-commit … -- -m "docs(plan): acceptance record, AC5 and AC6 evidence (issue 424)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing, and `git diff --stat CODE_HEAD..HEAD -- python tests lib justfile home/common/claude-code home/common/agent-skills/scripts home/common/agent-skills/skills` prints nothing.
