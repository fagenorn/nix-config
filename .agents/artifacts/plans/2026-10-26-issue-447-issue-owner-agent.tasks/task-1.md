# Task 1: Probe the body-less `issue-owner` before code lands; acceptance record

Spec § The definition, § No body, § Evidence run, per D2, D6, D7 and D8. Before any code changes, confirm on mbp that Claude Code 2.1.310 honours the definition Task 2 will commit: one `claude -p` probe in a scratch clone at base, with the definition as a git-excluded project copy, dispatches one `general-purpose` control and one `issue-owner` in the foreground and one `issue-owner` in the background with one identical brief. Each subagent lists its tools and dispatches one `Explore` child. This task changes no code and commits only the acceptance record. A value that misses its threshold is recorded as observed, never tuned.

**Files:**
- Create: `.agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md`

**Interfaces:**
- Consumes: the deployed `claude` (2.1.310); `agent_tools.transcript_calls.read_transcript(handle)`, whose `.calls[0].context` is input + cache read + cache write of the first request; `just agent-costs --report cache --projects-dir <root> --events-since <t> --events-before <t>`.
- Produces: the acceptance record with rows `AC1`–`AC3`, `AC3` filled, sections `## Feasibility`, `## Probe output` and `## Post-merge check (AC3)`; the definition's sha256 `02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56` (248 bytes), which Task 2's file must match.

**Invariants:**
- Host `mbp` (`hostname -s`); `git status --short -- home tests python justfile lib` prints nothing; this task's commit changes no path outside the acceptance record.
- The sandbox is a fresh local clone of this worktree checked out at `ca6ba1ae2b37e56c1361a8656c29af1f39b89348`; only `.claude/agents/issue-owner.md` is added, excluded through the clone's own `.git/info/exclude` (D6).
- The probe runs with `--model sonnet`, `--dangerously-skip-permissions`, `--output-format stream-json --verbose`, `--max-budget-usd 8`, `CLAUDE_ACCOUNT=<the caller's account>`, and unset `ENABLE_CLAUDEAI_MCP_SERVERS`, `CLAUDE_CODE_PLUGIN_DIRS` and `CLAUDE_ACCOUNT_LAUNCHER`; no other environment change (D8: no eval stub).
- Stop rules (D7): BLOCKED when the foreground `issue-owner` was dispatched but did not spawn or return, its child did not return `anis`, it lacks `Agent` (`Task`) or a kept tool its control listed (`Skill`, `Bash`, `Read`, `Edit`, `Write`, `ToolSearch`; `.checks.lost_tools`), or the control carried at least one listed tool and the `issue-owner` kept every one the control carried. A listed tool the control carried and the `issue-owner` kept, while another was removed, is reported as DONE_WITH_CONCERNS naming it; no launch flag, no body.

- [ ] **Step 1: Check the preconditions**

From the worktree root, `SCRATCH` being the path `launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>` prints:

```bash
hostname -s                                          # expect: mbp
git status --short -- home tests python justfile lib # expect: no output
CODE_HEAD=$(git rev-parse HEAD)
ACCOUNT=$(claude-account active)                     # a profile name or default
readlink -f "$(command -v claude)"; claude --version # expect: 2.1.310 (Claude Code)
P="$SCRATCH/probe-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir "$P"   # one fresh directory per attempt
```

Keep every value for Conditions. A different host, a dirty tree, another version or an `ACCOUNT` of the form `custom (…)` stops the task as BLOCKED, naming which.

- [ ] **Step 2: Write the definition, prompt, probe and measurement (scratch only, never committed)**

`$P/issue-owner.md` — exactly these seven lines, ending in a newline; check `shasum -a 256 "$P/issue-owner.md"` prints `02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56`:

```text
---
name: issue-owner
description: Owns one tracker issue for the from-issue and orchestrate-issues owner sites; not for other work.
model: opus
effort: high
disallowedTools: Artifact, ArtifactComments, ArtifactData, mcp__claude_ai_Claude_Docs
---
```

`$P/prompt.txt`:

```text
Make exactly three Agent tool calls, in this order, and no other tool call yourself. Give each the text between the two BRIEF lines below, verbatim, as its prompt.

1. subagent_type "general-purpose", model "opus", effort "high", description "Probe general-purpose", in the foreground.
2. subagent_type "issue-owner", model "opus", effort "high", description "Probe issue-owner", in the foreground.
3. subagent_type "issue-owner", model "opus", effort "high", description "Probe issue-owner background", with run_in_background true; then wait for its completion notification.

When all three have reported, reply with exactly three lines, each `<description>: <that subagent's CHILD line>`.

BRIEF
This is a measurement probe; do exactly this and nothing else.
1. Before any tool call, write one line starting `TOOLS:` followed by the names of every tool you can call, comma-separated: each tool you can call directly, then each deferred tool named in your context.
2. Dispatch exactly one subagent with the Agent tool: subagent_type "Explore", description "Read vars username", prompt "Read vars/default.nix in the current directory and report the value of `username`. Reply with one line: that value."
3. Reply with exactly two lines: the TOOLS line from step 1, then `CHILD: <the subagent's one-line answer>`, or `CHILD: none (<reason>)` if you could not dispatch it.
BRIEF
```

`$P/probe.sh`:

```bash
#!/usr/bin/env bash
# One issue-447 probe (D6, D7): probe.sh <worktree> <probe dir> <account>
set -euo pipefail
wt=$1 p=$2 account=$3
base=ca6ba1ae2b37e56c1361a8656c29af1f39b89348
sb="$p/sandbox"
utc() { python3 -c 'import datetime as d, sys; print((d.datetime.now(d.timezone.utc) + d.timedelta(seconds=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"; }
if [ -e "$sb" ]; then echo "probe: $sb already exists" >&2; exit 2; fi
git clone --quiet "$wt" "$sb"
git -C "$sb" checkout --quiet --detach "$base"
printf '.claude/\n' >> "$sb/.git/info/exclude"
mkdir -p "$sb/.claude/agents"
cp "$p/issue-owner.md" "$sb/.claude/agents/issue-owner.md"
start=$(utc 0)
status=0
( cd "$sb" && env -u ENABLE_CLAUDEAI_MCP_SERVERS -u CLAUDE_CODE_PLUGIN_DIRS -u CLAUDE_ACCOUNT_LAUNCHER \
    CLAUDE_ACCOUNT="$account" claude -p "$(cat "$p/prompt.txt")" --model sonnet \
    --dangerously-skip-permissions --output-format stream-json --verbose --max-budget-usd 8 \
    < /dev/null > "$p/run.jsonl" 2> "$p/run.err" ) || status=$?
end=$(utc 1)
printf '%s %s\n' "$start" "$end" > "$p/window"
sid=$(jq -r 'select(.type == "result") | .session_id' "$p/run.jsonl")
found=$(find "$HOME/.claude/projects" "$HOME/.claude-accounts/profiles/$account/projects" \
  -maxdepth 2 -name "$sid.jsonl" 2>/dev/null || true)
if [ "$(printf '%s\n' "$found" | grep -c .)" != 1 ]; then echo "probe: no single transcript for $sid" >&2; exit 1; fi
project=$(dirname "$found"); copy="$p/projects/$(basename "$project")"
mkdir -p "$copy"
cp "$found" "$copy/"
if [ -d "$project/$sid" ]; then cp -R "$project/$sid" "$copy/"; fi
echo "probe: exit $status session $sid window $start $end"
exit "$status"
```

`$P/measure.py`:

```python
"""Issue-447 probe measurement (D6, D7, D8): measure.py <probe dir>."""
import json
import sys
from pathlib import Path

from agent_tools.transcript_calls import read_transcript

LISTED = ("Artifact", "ArtifactComments", "ArtifactData", "mcp__claude_ai_Claude_Docs")
KEPT = ("Agent", "Skill", "Bash", "Read", "Edit", "Write", "ToolSearch")


def records(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def matches(listed, name):
    return name == listed or (listed.startswith("mcp__") and name.startswith(listed + "__"))


def texts(path):
    out = []
    for value in records(path):
        content = (value.get("message") or {}).get("content") if value.get("type") == "assistant" else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "text":
                out.extend(block.get("text", "").splitlines())
    return out


def last(lines, prefix):
    found = [line.strip() for line in lines if line.strip().startswith(prefix)]
    return found[-1] if found else None


def subagent(path):
    meta = json.loads(path.with_name(path.stem + ".meta.json").read_text(encoding="utf-8"))
    with open(path, encoding="utf-8", errors="replace") as handle:
        calls = read_transcript(handle).calls
    deferred = set()
    for value in records(path):
        body = value.get("attachment") if value.get("type") == "attachment" else None
        if isinstance(body, dict) and body.get("type") == "deferred_tools_delta":
            deferred |= set(body.get("addedNames", []))
    lines = texts(path)
    tools_line = last(lines, "TOOLS:")
    listed = [n.strip().strip("`") for n in tools_line[len("TOOLS:"):].split(",")] if tools_line else []
    names = {"Agent" if n == "Task" else n for n in set(listed) | deferred}
    first = calls[0] if calls else None
    return {
        "id": path.stem.removeprefix("agent-"),
        "agent_type": meta.get("agentType"),
        "description": meta.get("description"),
        "background": meta.get("requestShape") == "background",
        "parent": meta.get("parentAgentId"),
        "first_request": None if first is None else {
            "input": first.usage["input_tokens"], "write": first.usage["cache_creation_input_tokens"],
            "read": first.usage["cache_read_input_tokens"], "total": first.context},
        "deferred_added": sorted(deferred),
        "listed": {tool: any(matches(tool, n) for n in names) for tool in LISTED},
        "names": sorted(names),
        "tools_line": tools_line,
        "child_line": last(lines, "CHILD:"),
        "last_line": lines[-1].strip() if lines else None,
    }


def root_dispatches(path):
    calls, errors = [], set()
    for value in records(path):
        content = (value.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                given = block.get("input") or {}
                calls.append({"id": block.get("id"), "subagent_type": given.get("subagent_type"),
                              "background": bool(given.get("run_in_background"))})
            elif block.get("type") == "tool_result" and block.get("is_error"):
                errors.add(block.get("tool_use_id"))
    for call in calls:
        call["error"] = call.pop("id") in errors
    return calls


def status(control, owner):
    if owner is None:
        return "not observed"
    if not control:
        return "not in pool"
    return "kept" if owner else "removed"


def main():
    probe = Path(sys.argv[1])
    stream = list(records(probe / "run.jsonl"))
    init = next((v for v in stream if v.get("type") == "system" and v.get("subtype") == "init"), None)
    result = next((v for v in stream if v.get("type") == "result"), {})
    roots = sorted((probe / "projects").glob("*/*.jsonl"))
    rows = [subagent(p) for p in sorted((probe / "projects").glob("*/*/subagents/agent-*.jsonl"))]
    dispatches = root_dispatches(roots[0]) if len(roots) == 1 else []
    gp = [r for r in rows if r["agent_type"] == "general-purpose"]
    fg = [r for r in rows if r["agent_type"] == "issue-owner" and not r["background"]]
    bg = [r for r in rows if r["agent_type"] == "issue-owner" and r["background"]]
    void = []
    if result.get("subtype") != "success" or result.get("is_error"):
        void.append(f"result {result.get('subtype')!r} is_error {result.get('is_error')!r}")
    if init is None or len(roots) != 1:
        void.append(f"init line {'present' if init else 'missing'}, root transcripts {len(roots)}")
    if not any(d["subagent_type"] == "general-purpose" for d in dispatches) or len(gp) != 1:
        void.append(f"general-purpose control: {len(gp)} transcripts")
    if not any(d["subagent_type"] == "issue-owner" and not d["background"] for d in dispatches):
        void.append("root never dispatched a foreground issue-owner")
    if len(fg) > 1 or len(bg) > 1:
        void.append(f"issue-owner transcripts: {len(fg)} foreground, {len(bg)} background")
    summary = {"session_id": result.get("session_id"), "cost_usd": result.get("total_cost_usd"),
               "root_tools": sorted((init or {}).get("tools", [])), "dispatches": dispatches,
               "rows": rows, "void": void}
    if not void:
        control, owner, back = gp[0], (fg[0] if fg else None), (bg[0] if bg else None)
        children = [r for r in rows if owner and r["agent_type"] == "Explore" and r["parent"] == owner["id"]]
        spawned = owner is not None and owner["first_request"] is not None and owner["tools_line"] is not None
        child_ok = (spawned and (owner["child_line"] or "").lower() == "child: anis"
                    and any((c["last_line"] or "").strip("` ").lower() == "anis" for c in children))
        per_tool = {tool: {"control": "present" if control["listed"][tool] else "not in pool",
                           "foreground": status(control["listed"][tool], owner["listed"][tool] if owner else None),
                           "background": status(control["listed"][tool], back["listed"][tool] if back else None)}
                    for tool in LISTED}
        carried = [t for t in LISTED if control["listed"][t]]
        smaller = control["first_request"]["total"] - owner["first_request"]["total"] if spawned else None
        artifact = "Artifact" in summary["root_tools"] and control["listed"]["Artifact"]
        summary["checks"] = {
            "spawned_and_returned": spawned, "child_returned_anis": child_ok,
            "lost_tools": [t for t in KEPT if t in control["names"] and not (owner and t in owner["names"])],
            "kept_tools": bool(owner and "Agent" in owner["names"])
            and not [t for t in KEPT if t in control["names"] and t not in owner["names"]],
            "per_tool": per_tool,
            "control_carried": carried,
            "kept_listed": [t for t in carried if owner and owner["listed"][t]],
            "first_request_total": {"general-purpose": control["first_request"]["total"],
                                    "issue-owner": owner["first_request"]["total"] if spawned else None,
                                    "issue-owner-background": (back["first_request"] or {}).get("total") if back else None},
            "smaller_by": smaller, "root_pool_artifact": artifact,
            "ac3": ("pending post-merge (D8)" if not artifact
                    else "met" if smaller is not None and smaller >= 11000 and child_ok else "missed"),
        }
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the probe (foreground, timeout 1200 s)**

```bash
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash "$P/probe.sh" "$PWD" "$P" "$ACCOUNT"
```

Expected: `probe: exit 0 session <id> window <start> <end>`. A non-zero exit stops the task as BLOCKED with `tail -5 "$P/run.err"`.

- [ ] **Step 4: Read the run**

```bash
read -r start end < "$P/window"
just agent-costs --report cache --projects-dir "$P/projects" \
  --events-since "$start" --events-before "$end" > "$P/report.txt"
sed -n '/^Subagent start-up/,/^NOTE:/p' "$P/report.txt"
PYTHONPATH="$PWD/python" python3 "$P/measure.py" "$P" > "$P/summary.json"
jq '{void, root_tools: [.root_tools[] | select(test("Artifact|Docs"))], checks}' "$P/summary.json"
```

Rerun Steps 1 (new `P`, copy the four Step 2 files into it) to 4 once, recording both attempts, when `.void` is non-empty or `.checks.control_carried` is empty (the connector had not connected). A second void stops the task as BLOCKED with the void list. Then apply the stop rules (Invariants) to `.checks`.

- [ ] **Step 5: Write the acceptance record**

Create `.agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md` holding, in order:

1. The heading `# Acceptance record — issue 447`.
2. The sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/447).`
3. One table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and rows `AC1` to `AC3`:
   - `Criterion`: the issue's criterion line verbatim without its `- [ ] ` checkbox (`gh issue view 447 --repo fagenorn/nix-config --json body --jq .body`), each `|` escaped as `\|`.
   - `Kind` and `Check or command`: copied from the plan root's Acceptance map.
   - `AC1`, `AC2`: `Observed` `in final verification`; `Commit`, `Conditions` `—`.
   - `AC3`: `Observed` `probe: general-purpose <g> → issue-owner <i> tokens (first request), smaller by <d>; issue-owner child: returned anis|<child_line>; root pool Artifact: present|absent; threshold 11,000: met|missed|pending post-merge (D8)`. `Commit` is `CODE_HEAD`'s short SHA. `Conditions`: host `mbp`, `ACCOUNT`, the deployed `claude` path and `--version`, the definition sha256, the probe invocation, the window, session id and cost, any retry, `not tuned`.
   - `Verdict`: `—` in every row.
4. `## Feasibility` — one table `Tool | general-purpose control | issue-owner foreground | issue-owner background`, rows `Artifact`, `ArtifactComments`, `ArtifactData`, `mcp__claude_ai_Claude_Docs` from `.checks.per_tool`; then one line each for `spawned and returned`, `child returned anis`, `kept tools (Agent/Task, Skill, Bash, Read, Edit, Write, ToolSearch)`, and every tool in `.checks.kept_listed` named as kept by frontmatter. A tool `not in pool` in the control is confirmed by the post-merge check.
5. `## Probe output` — the `sed` output of Step 4 in one fenced `text` block, then `summary.json` in one fenced `json` block.
6. `## Post-merge check (AC3)` — this text, with `<SWITCH>` and `<END>` left for whoever runs it after the user's `just switch` (UTC, `%Y-%m-%dT%H:%M:%SZ`; `<END>` is the instant the check runs, and `agent-costs` requires both bounds together):

   ```text
   just agent-costs --report cache --events-since <SWITCH> --events-before <END>              # after: issue-owner row
   just agent-costs --report cache --events-since <SWITCH minus 7 days> --events-before <SWITCH>  # before: general-purpose row
   ```

   Met when the before table's `general-purpose` (1st write + 1st read) minus the after table's `issue-owner` (1st write + 1st read) is at least 11,000 tokens, and `jq -r 'select(.type == "attachment" and .attachment.type == "deferred_tools_delta") | .attachment.addedNames[]'` over every subagent transcript whose `meta.json` `agentType` is `issue-owner` since `<SWITCH>` prints no `Artifact`, `ArtifactComments`, `ArtifactData` or `mcp__claude_ai_Claude_Docs__*` name. Record the two rows, `<SWITCH>`, `<END>`, the difference and the verdict in row `AC3`; until then the issue is held open (D8).

Report DONE_WITH_CONCERNS naming each tool in `.checks.kept_listed` and any missed threshold.

- [ ] **Step 6: Verify**

```bash
set -e
f=.agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md
test "$(grep -c '^| AC[1-3] |' "$f")" = 3
grep -q '^| AC3 |.*smaller by' "$f"
grep -q '02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56' "$f"
for s in '## Feasibility' '## Probe output' '## Post-merge check (AC3)'; do grep -qx "$s" "$f"; done
jq -e '(.void | length) == 0 and .checks.spawned_and_returned and .checks.child_returned_anis and .checks.kept_tools and ((.checks.control_carried | length) == 0 or (.checks.kept_listed | length) < (.checks.control_carried | length))' "$P/summary.json"
```

Expected: every command exits 0. The `jq` line fails at the commit you start from (no probe has run) and whenever a D7 stop rule applies.

- [ ] **Step 7: Commit**

```bash
git add .agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, issue-owner probe (issue 447)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing, and `git diff --stat "$CODE_HEAD"..HEAD -- home tests python justfile lib` prints nothing.
