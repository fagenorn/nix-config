# Task 4: AC3 start-up evidence and the acceptance record

Spec § Evidence runs (start-up overhead), per D7 and D9. Measure the start-up bill of one `reviewer-lite` and one `mechanic` subagent twice on mbp, without activation: *before* with the deployed `claude`, the deployed settings and the base agent definitions; *after* with the built `claude-orchestrate`, `--settings` the built settings file and this branch's agent definitions. Each run is read through `just agent-costs --report cache` over its own isolated transcript copy and window, and through `agent_cache_report.scan_transcript` for exact values. This task changes no code: a value that misses its threshold is recorded as observed, never tuned (D7).

**Files:**
- Create: `.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md`

**Interfaces:**
- Consumes: Task 1's agent definitions at `HEAD`; Task 3's `<package>/bin/claude-orchestrate`; Task 2's `skillOverrides` in the built settings; `just agent-costs --report cache --projects-dir <root> --events-since <t> --events-before <t>` and `agent_tools.agent_cache_report.transcript_jobs(root, None)` / `scan_transcript((path, is_root), since=None, before=None, threshold=…)`, whose `startup` is `{"write": int, "read": int, "attachments": {name: chars}}` or `None`.
- Produces: the acceptance record with rows `AC1`–`AC4` in that order, `AC3` filled; Task 5 fills `AC4`; the sdd controller writes every `Verdict`.

**Invariants:**
- Host `mbp` (`hostname -s`); `git status --short -- home tests justfile python lib` prints nothing before the runs; this task's commit changes no path outside the acceptance record.
- Both sandboxes are fresh local clones of this worktree checked out at `04a396606d69fe6b720596c20846934b040abaa6`, so the project `CLAUDE.md` and its import are identical in both; only `.claude/agents/{mechanic,reviewer-lite}.md` differ (base content before, `HEAD` content after), excluded through each clone's own `.git/info/exclude` (D9).
- Both runs use the same prompt file, `--model sonnet`, `--dangerously-skip-permissions`, `--output-format json`, `--max-budget-usd 5`, `CLAUDE_ACCOUNT=<the caller's account>`, and unset `ENABLE_CLAUDEAI_MCP_SERVERS`, `CLAUDE_CODE_PLUGIN_DIRS` and `CLAUDE_ACCOUNT_LAUNCHER` (D9).
- Thresholds, from exact `scan_transcript` values: `reviewer-lite` (write + read) before minus after ≥ 2,500 tokens; `mechanic` `skill_listing` characters (before − after) / before ≥ 0.30; no `claude.ai …` name in any after-run subagent's `mcp_instructions_delta` `addedNames`.
- A run is void, never a measurement, when its result is not `success`, its subagents are not exactly one `mechanic` and one `reviewer-lite`, the `mechanic` start-up lacks `skill_listing`, or the `instructions` start-up attachment is absent from a before-run subagent or present in an after-run one (D9).

- [ ] **Step 1: Check the preconditions and build**

From the worktree root, `SCRATCH` being the path `launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>` prints:

```bash
hostname -s                                         # expect: mbp
git status --short -- home tests justfile python lib  # expect: no output
CODE_HEAD=$(git rev-parse HEAD)                     # Task 3's commit or later
AC3="$SCRATCH/ac3-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir "$AC3"   # one fresh directory per attempt
```

Run the **Build** (Global Constraints), then:

```bash
PKG=$(nix-store --query --requisites ./result | grep -- '-claude-code-with-accounts-[^/]*$')
SETTINGS=$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')
test -x "$PKG/bin/claude-orchestrate"
ACCOUNT=$(claude-account active)                    # a profile name or default
readlink -f "$(command -v claude)"; claude --version; "$PKG/bin/claude" --version
jq -n --slurpfile a "$SETTINGS" --slurpfile b "$HOME/.claude/settings.json" \
  '[($a[0]|keys[]), ($b[0]|keys[])] | unique | map(select($a[0][.] != $b[0][.]))'
```

Keep every value for Conditions. A different host, a dirty tree, a missing `claude-orchestrate` or an `ACCOUNT` of the form `custom (…)` stops the task as BLOCKED, naming which.

- [ ] **Step 2: Write the harness, the prompt and the measurement (scratch only, never committed)**

`$AC3/prompt.txt`:

```text
Dispatch exactly two subagents with the Agent tool, one after the other, each in the foreground, and make no other tool call yourself.

First: subagent_type "mechanic", description "Count flake.nix lines", prompt:
Run `wc -l flake.nix` in the current directory. Status vocabulary: DONE or BLOCKED. Report shape: one line, `DONE <line count>`.

Second: subagent_type "reviewer-lite", description "Lane-verify flake.nix", prompt:
Mode: lane verification. Declared lane: mechanical. Diff boundary: `git diff HEAD~1 HEAD -- flake.nix`. Verification command: `git diff --stat HEAD~1 HEAD -- flake.nix`. Verdict vocabulary: APPROVED or REJECTED. Report shape: one line, the verdict. Length budget: one line.

When both have answered, reply with their two one-line reports, one per line.
```

`$AC3/harness.sh`:

```bash
#!/usr/bin/env bash
# One AC3 run (issue 425 D7, D9): harness.sh before|after <worktree> <ac3 dir> <account> [<package> <settings>]
set -euo pipefail
label=$1 wt=$2 ac3=$3 account=$4
base=04a396606d69fe6b720596c20846934b040abaa6
sb="$ac3/$label"
utc() { python3 -c 'import datetime as d, sys; print((d.datetime.now(d.timezone.utc) + d.timedelta(seconds=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"; }
case "$label" in
  before) rev=$base ;;
  after) rev=$(git -C "$wt" rev-parse HEAD) ;;
  *) echo "harness: label must be before or after" >&2; exit 2 ;;
esac
if [ -e "$sb" ]; then echo "harness: $sb already exists" >&2; exit 2; fi
git clone --quiet "$wt" "$sb"
git -C "$sb" checkout --quiet --detach "$base"
printf '.claude/\n' >> "$sb/.git/info/exclude"
mkdir -p "$sb/.claude/agents"
for agent in mechanic reviewer-lite; do
  git -C "$wt" show "$rev:home/common/claude-code/agents/$agent.md" > "$sb/.claude/agents/$agent.md"
done
if [ "$label" = before ]; then launch=(claude); else launch=("$5/bin/claude-orchestrate" --settings "$6"); fi
start=$(utc 0)
status=0
( cd "$sb" && env -u ENABLE_CLAUDEAI_MCP_SERVERS -u CLAUDE_CODE_PLUGIN_DIRS -u CLAUDE_ACCOUNT_LAUNCHER \
    CLAUDE_ACCOUNT="$account" "${launch[@]}" -p "$(cat "$ac3/prompt.txt")" --model sonnet \
    --dangerously-skip-permissions --output-format json --max-budget-usd 5 \
    < /dev/null > "$ac3/$label.json" 2> "$ac3/$label.err" ) || status=$?
end=$(utc 1)
printf '%s %s\n' "$start" "$end" > "$ac3/$label.window"
sid=$(jq -r .session_id "$ac3/$label.json")
transcript=$(find "$HOME/.claude/projects" -maxdepth 2 -name "$sid.jsonl")
if [ "$(printf '%s\n' "$transcript" | grep -c .)" != 1 ]; then echo "harness: no single transcript for $sid" >&2; exit 1; fi
project=$(dirname "$transcript"); copy="$ac3/$label-projects/$(basename "$project")"
mkdir -p "$copy"
cp "$transcript" "$copy/"
cp -R "$project/$sid" "$copy/"
echo "harness: $label exit $status session $sid window $start $end"
exit "$status"
```

`$AC3/measure.py`:

```python
"""AC3 measurement over the two isolated harness runs (issue 425 D7, D9)."""
import json
import sys
from pathlib import Path

from agent_tools import agent_cache_report as report

HIDDEN = {
    "artifact-design", "artifact-diagramming", "artifact-capabilities", "dataviz",
    "anthropic-skills:docx", "anthropic-skills:pptx", "anthropic-skills:xlsx",
    "anthropic-skills:pdf", "anthropic-skills:google-workspace", "anthropic-skills:morning",
    "anthropic-skills:import-memory", "anthropic-skills:skill-creator",
}


def sent(path):
    """The claude.ai servers, claude.ai tool names and hidden skills one transcript was sent."""
    servers, tools, hidden = set(), set(), set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            body = value.get("attachment") if value.get("type") == "attachment" else None
            if not isinstance(body, dict):
                continue
            if body.get("type") == "mcp_instructions_delta":
                servers |= {n for n in body.get("addedNames", []) if n.startswith("claude.ai ")}
            elif body.get("type") == "deferred_tools_delta":
                names = body.get("addedNames", []) + body.get("surfacedNames", [])
                tools |= {n for n in names if n.startswith("mcp__claude_ai")}
            elif body.get("type") == "skill_listing":
                hidden |= set(body.get("names", [])) & HIDDEN
    return {"claude_ai_servers": sorted(servers), "claude_ai_tools": len(tools),
            "hidden_listed": sorted(hidden)}


def run(ac3, label):
    result = json.loads((ac3 / f"{label}.json").read_text(encoding="utf-8"))
    rows = []
    for path, is_root in report.transcript_jobs(ac3 / f"{label}-projects", None):
        scanned = report.scan_transcript((path, is_root), since=None, before=None,
                                         threshold=report.DEFAULT_CONTEXT_THRESHOLD)
        rows.append({"agent_type": scanned["agent_type"], "startup": scanned["startup"], **sent(path)})
    subagents = [row for row in rows if row["agent_type"] != "main"]
    void = []
    if result.get("subtype") != "success" or result.get("is_error"):
        void.append(f"result {result.get('subtype')!r} is_error {result.get('is_error')!r}")
    kinds = sorted(row["agent_type"] for row in subagents)
    if kinds != ["mechanic", "reviewer-lite"]:
        void.append(f"subagents {kinds}")
    for row in subagents:
        names = (row["startup"] or {}).get("attachments", {})
        if ("instructions" in names) != (label == "before"):
            void.append(f"{row['agent_type']}: instructions attachment {'missing' if label == 'before' else 'present'}")
        if row["agent_type"] == "mechanic" and "skill_listing" not in names:
            void.append("mechanic: no skill_listing")
    return {"session_id": result.get("session_id"), "cost_usd": result.get("total_cost_usd"),
            "rows": rows, "void": void}


def first_request(row):
    return row["startup"]["write"] + row["startup"]["read"]


def listing(row):
    return row["startup"]["attachments"]["skill_listing"]


def main():
    ac3 = Path(sys.argv[1])
    summary = {label: run(ac3, label) for label in ("before", "after")}
    if not summary["before"]["void"] and not summary["after"]["void"]:
        before = {row["agent_type"]: row for row in summary["before"]["rows"]}
        after = {row["agent_type"]: row for row in summary["after"]["rows"]}
        smaller = first_request(before["reviewer-lite"]) - first_request(after["reviewer-lite"])
        share = (listing(before["mechanic"]) - listing(after["mechanic"])) / listing(before["mechanic"])
        servers = sorted({name for row in summary["after"]["rows"] if row["agent_type"] != "main"
                          for name in row["claude_ai_servers"]})
        summary["thresholds"] = {
            "reviewer_lite_first_request_smaller_by": smaller, "met_2500": smaller >= 2500,
            "mechanic_listing_smaller_by": round(share, 4), "met_30pct": share >= 0.30,
            "after_subagent_claude_ai_servers": servers, "met_none": not servers,
        }
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run before, then after (foreground, timeout 900 s each)**

```bash
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash "$AC3/harness.sh" before "$PWD" "$AC3" "$ACCOUNT"
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash "$AC3/harness.sh" after "$PWD" "$AC3" "$ACCOUNT" "$PKG" "$SETTINGS"
```

Expected: each prints `harness: <label> exit 0 session <id> window <start> <end>`. A non-zero exit stops the task as BLOCKED with `tail -5 "$AC3/<label>.err"`.

- [ ] **Step 4: Read the runs**

```bash
for label in before after; do
  read -r start end < "$AC3/$label.window"
  just agent-costs --report cache --projects-dir "$AC3/$label-projects" \
    --events-since "$start" --events-before "$end" > "$AC3/$label-report.txt"
  sed -n '/^Subagent start-up/,/^NOTE:/p' "$AC3/$label-report.txt"
done
PYTHONPATH="$PWD/python" python3 "$AC3/measure.py" "$AC3" > "$AC3/summary.json"
jq '{void: [.before.void, .after.void], thresholds}' "$AC3/summary.json"
```

Each start-up table holds exactly one `mechanic` and one `reviewer-lite` row, matching `summary.json`'s values within the table's two-decimal `k` rounding.

If `.before.void` or `.after.void` is non-empty only because of a `result …` or `subagents …` entry (the root did not dispatch as told), rerun Steps 3–4 once in a fresh `AC3` directory made as in Step 1 (copy the three Step 2 files into it first) and record both attempts. Any `instructions` or `skill_listing` entry, or a second void, stops the task as BLOCKED with the void list: the copies under test did not load, which is not a measurement (D9).

- [ ] **Step 5: Write the acceptance record**

Create `.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md` holding, in order:

1. The heading `# Acceptance record — issue 425`.
2. The sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/425).`
3. One table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and rows `AC1` to `AC4` in order:
   - `Criterion`: the issue's criterion line verbatim without its `- [ ] ` checkbox (`gh issue view 425 --repo fagenorn/nix-config --json body --jq .body`), each `|` escaped as `\|`.
   - `Kind` and `Check or command`: copied from the plan root's Acceptance map.
   - `AC1`: `Observed` `in final verification`; `Commit`, `Conditions` `—`.
   - `AC2`: `Observed` `in final verification; anis-desktop evaluation by the PR's Nix Eval check (D10)`; `Commit`, `Conditions` `—`.
   - `AC3`: `Observed` holds `reviewer-lite first request <before> → <after> tokens, smaller by <n> (threshold 2,500: met|missed)`, `mechanic skill listing <before> → <after> characters, smaller by <p> % (threshold 30 %: met|missed)`, `after-run subagent claude.ai MCP servers: none|<names> (threshold none: met|missed)`, and the after-run `hidden_listed` and `claude_ai_tools` values. `Commit` is `CODE_HEAD`'s short SHA. `Conditions` names host `mbp`, `ACCOUNT`, the deployed `claude` path and both `--version` outputs, `$PKG`, `$SETTINGS`, the settings keys that differ from the deployed file, both harness invocations, both windows, both session ids and costs, the before run's `claude_ai_servers`, any retry, and `not tuned (D7)`.
   - `AC4`: `Observed` `pending (Task 5)`; `Commit`, `Conditions` `—`.
   - `Verdict`: `—` in every row.
4. A section `## AC3 run output` with `### Before` and `### After`, each holding that run's start-up section (the `sed` output of Step 4) in one fenced `text` block, then `### Measurement` holding `summary.json` in one fenced `json` block.

When a threshold is missed, report the task DONE_WITH_CONCERNS naming the value and its threshold.

- [ ] **Step 6: Verify**

```bash
set -e
f=.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md
test "$(grep -c '^| AC[1-4] |' "$f")" = 4
grep -q '^| AC3 |.*reviewer-lite first request' "$f"
grep -q '^## AC3 run output$' "$f"
jq -e '(.before.void | length) == 0 and (.after.void | length) == 0 and (.thresholds | has("met_2500"))' "$AC3/summary.json"
```

Expected: every command exits 0 — four rows, AC3 filled from a run that is not void.

- [ ] **Step 7: Commit**

```bash
git add .agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, AC3 start-up evidence (issue 425)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing, and `git diff --stat "$CODE_HEAD"..HEAD -- home tests justfile python lib` prints nothing.
