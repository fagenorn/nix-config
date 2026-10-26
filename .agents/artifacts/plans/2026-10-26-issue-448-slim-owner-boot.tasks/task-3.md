# Task 3: Two-host baseline, cut projections and keep verdicts

Spec § Evidence and threshold (Baseline, both hosts) and § The keep rule; per D5, D11, D12, D15, D16, D18. The whole task runs **before merge**, and nothing in it is held. It runs on mbp, reads anis-desktop through a read-only copy, and commits only the acceptance record: aggregate figures, no transcript data.

**Files:**
- Create: `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md`
- Scratch only, never committed: `$S/scripts/select-sessions.sh`, `$S/scripts/extract.py`, `$S/scripts/project.py`, `$S/anis-desktop.b64`, `$S/anis-desktop.err`, `$S/anis-desktop/projects/`, `$S/baseline.json`, `$S/baseline.txt`. `S="$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)/i448"`.

**Interfaces:**
- Consumes: Tasks 1–2's `--report boot` with labelled roots, document `agent-boot-report` v1.
- Produces, for Tasks 4–7:
  - The record's AC table (rows `AC1`–`AC3`, with evidence columns `—`) and three sections, `## Method`, `## Baseline (two hosts)` and `## Cut projections and verdicts`.
  - The cut table: one row per cut 1–5, `| <cut> | <rule> | <inputs> | <projection> | <verdict> | <built> |`. The verdict is `keep` or `reject (<reason>)`. Built is `—` for a kept cut until its task fills it, and `not built` for a rejected one. Tasks 4–6 start by reading their cut's verdict.
  - The headline `B without tool schemas` for host `all`, `fresh`, phase group `all`, and the per-stratum fresh counts and means that Task 7's protocol copies.

**Invariants:**
- The baseline uses exactly two roots, labelled `mbp` and `anis-desktop`, over `--events-since 2026-10-24T00:00:00Z --events-before <T>`, with `T` the UTC second the report is run. An mbp-only baseline is never recorded as the two-host one (D15, D18).
- The record holds no transcript path, session ID, run ID or scratch path.
- The worktree's only change is the record. Every anis-desktop byte stays under `$S`, and `$S` is removed once the record is committed.

- [ ] **Step 1: Preconditions and scratch**

Run `bash -c 'test "$(hostname -s)" = mbp'`. Expected: exit 0; any other host stops the task as BLOCKED. Create `$S/scripts` and `$S/anis-desktop/projects`.

- [ ] **Step 2: Copy anis-desktop's owner sessions (D18)**

Write `$S/scripts/select-sessions.sh` exactly as follows. It runs in anis-desktop's WSL login shell, where `python3` exists:

```bash
set -euo pipefail
python3 - "$1" <<'PY'
import base64, datetime, hashlib, io, os, sys, tarfile

since = datetime.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp()
root = os.path.expanduser("~/.claude/projects")


def owner(path):
    """Modified since the window start and naming a registering helper call."""
    try:
        if os.path.getmtime(path) < since:
            return False
        with open(path, "r", errors="replace") as handle:
            return any("--run-id" in line and "--action-id" in line
                       and ("workflow-state" in line or "sdd-gate" in line) for line in handle)
    except OSError:
        return False


projects = sorted(name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name)))
sessions = set()
for project in projects:
    base = os.path.join(root, project)
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if name.endswith(".jsonl") and owner(path):
            sessions.add(name[: -len(".jsonl")])
        elif os.path.isdir(os.path.join(path, "subagents")):
            for folder, _, files in os.walk(os.path.join(path, "subagents")):
                if any(f.endswith(".jsonl") and owner(os.path.join(folder, f)) for f in files):
                    sessions.add(name)
                    break
buffer, entries = io.BytesIO(), 0
with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
    for project in projects:
        for session in sorted(sessions):
            for member in (f"{session}.jsonl", f"{session}/subagents"):
                path = os.path.join(root, project, member)
                if os.path.exists(path):
                    archive.add(path, arcname=f"{project}/{member}")
                    entries += 1
data = buffer.getvalue()
sys.stderr.write(f"sessions={len(sessions)} entries={entries} bytes={len(data)} "
                 f"sha256={hashlib.sha256(data).hexdigest()}\n")
sys.stdout.write("BEGIN-I448\n" + base64.b64encode(data).decode("ascii") + "\nEND-I448\n")
PY
```

Write `$S/scripts/extract.py`. The markers make the copy immune to anything the login shell prints:

```python
import base64, hashlib, io, sys, tarfile

source, expected, target = sys.argv[1:4]
with open(source, "r", encoding="ascii", errors="replace") as handle:
    text = handle.read()
payload = text.split("BEGIN-I448\n", 1)[1].split("\nEND-I448", 1)[0]
data = base64.b64decode(payload, validate=True)
if hashlib.sha256(data).hexdigest() != expected:
    sys.exit("anis-desktop copy: sha256 mismatch")
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    archive.extractall(target, filter="data")
```

Run through `launch-scope exec`, timeout 1800 s:
`bash -c 'ssh -o BatchMode=yes -o ConnectTimeout=30 anis-desktop "wsl -e bash -l -s 2026-10-24T00:00:00Z" < "$1/scripts/select-sessions.sh" > "$1/anis-desktop.b64" 2> "$1/anis-desktop.err"' _ "$S"`.

Expected: exit 0, and `tail -1 "$S/anis-desktop.err"` matches `^sessions=[0-9]+ entries=[0-9]+ bytes=[0-9]+ sha256=[0-9a-f]{64}$`. Then run `python3 -I "$S/scripts/extract.py" "$S/anis-desktop.b64" <that sha256> "$S/anis-desktop/projects"`. Expected: exit 0, and `find "$S/anis-desktop/projects" -name '*.jsonl' | wc -l` is above 0.

On a non-zero exit, a malformed last line or a sha256 mismatch, run one bounded `sleep 60` and repeat the transfer once. A second failure stops the task as BLOCKED, reporting the stderr tail (D15, D18).

- [ ] **Step 3: Run the baseline**

`T="$(date -u +%Y-%m-%dT%H:%M:%SZ)"`. Then run through `launch-scope exec`, timeout 1800 s each:
- `bash -c 'PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_costs --report boot --format json --events-since 2026-10-24T00:00:00Z --events-before "$1" --projects-dir "mbp=$HOME/.claude/projects" --projects-dir "anis-desktop=$2/anis-desktop/projects" --top 100000 > "$2/baseline.json"' _ "$T" "$S"`
- the same without `--format json`, with `--top 30`, into `$2/baseline.txt`.

Expected: exit 0 both times. `jq '[.hosts[].label]' "$S/baseline.json"` prints `["mbp","anis-desktop"]`, and both hosts have at least one `fresh` boot (a host with none stops the task as BLOCKED: the criterion needs both).

- [ ] **Step 4: Project each cut (D16)**

Write `$S/scripts/project.py` and run it with `python3 -I`. It reads `$S/baseline.json` and the base documents through `git show ca6ba1ae:<path>`. `n` is the number of `fresh` boots over both hosts, and every projection is a sum over fresh boots divided by `n`, in tokens. A document's sections are split at lines starting `## ` (a `###` stays in its parent). The opening is the text before the first such line, frontmatter included.

- **Cut 1** (D6). `A = (median byte size of every *.md directly under .agents/artifacts/plans/ that has a sibling <stem>.tasks/ + median byte size of every task-*.md inside those directories) ÷ 2.44`, all at `ca6ba1ae` (expect about 8,630). The projection sums `max(0, buckets.plan_reads − A)` over `6-7` boots.
- **Cut 2** (D7). For `home/common/agent-skills/skills/from-issue/SKILL.md`, the share skipped is `s_g = 1 − (opening + Files beside this one + Lifecycle identity + Decision ledger (artifact discipline) + Skill-tool invocations + Dispatch, phase-budget and attempt-budget rules + Terminal return procedure + Suspension procedure + phase) ÷ file bytes`. The phase section is `Phase 5 — Standards review` for group `0-5` and `Phase 6 — Execute` for `6-7` (expect about 0.34 and 0.27). The projection sums `skills["from-issue"] × s_g`. It is an upper bound, because a retry carries no pack.
- **Cut 3** (D8). `share_A = When *not* to auto-resolve ÷ (opening + The self-answer pattern + When *not* to auto-resolve + Interface_version 2 delivery relay + Other Phase 5–7 routes)` of `from-issue/AUTO.md` (expect about 0.37). `share_D = Generic delegate ÷ file bytes` of `from-issue/delegated-owner.md` (expect about 0.13). The projection sums `skill_files["from-issue/AUTO.md"] × share_A + skill_files["from-issue/delegated-owner.md"] × share_D + skill_files["from-issue/ship-handoff.md"]` over `6-7` boots. The ship-handoff term is an upper bound, because a Phase-7 boot keeps that read.
- **Cut 4** (information, D9). The sum of `skills["sdd"] × (### Cumulative delivery gate + ### Review-package gate) ÷ file bytes` of `sdd/SKILL.md`, over `6-7` boots.
- **Cut 5** (information, D10). The mean `buckets.rereads`.

Verdict: cuts 1–3 are `keep` when the projection is at least 1,000, else `reject (projection under 1,000)`. Cut 4 is `reject (D9)` and cut 5 is `reject (D10)`, whatever their figures.

- [ ] **Step 5: Write the acceptance record**

Create the record with this skeleton, replacing every angle-bracketed slot with the measured value (copy the Criterion cells verbatim):

```markdown
# Acceptance record — issue 448

Baseline taken on host mbp from the `mbp` root (`~/.claude/projects`) and a read-only copy of `anis-desktop`'s (https://github.com/fagenorn/nix-config/issues/448); each row's Commit is the head its evidence was taken on.

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] `just agent-costs --report boot` reports per-owner and mean boot buckets. Measured by: unit tests on fixture transcripts. | code | <the plan's acceptance-map Check for AC1> | — | — | — | — |
| AC2 | [code] Kept cuts are pinned by contract tests. `just agent-workflow-tests`, `just agent-instruction-budget` (no raise label) and `just build` pass. | code | <AC2's Check> | — | — | — | — |
| AC3 | [evidence] The mean fresh-owner boot, excluding tool schemas, falls by at least 25k against the 2026-10-26 baseline on new owner transcripts. The replay sweep is re-run, and its chosen threshold is stated with reasons. | evidence | <AC3's Check> | — | — | — | — |

## Method

<Step 2's two scripts as fenced blocks, the transfer and extract commands, and Step 3's report command with `<window start>` and `<window end>` slots, so a later session can rerun them.>

## Baseline (two hosts)

Window 2026-10-24T00:00:00Z → <T>; head <12-char sha>; <sessions>/<entries> copied from anis-desktop; observed characters per token <x>; unsplit: mbp <n>, anis-desktop <n>.

| Host | Cohort | Phase group | Boots | B mean | B without tool schemas |
|------|--------|-------------|-------|--------|------------------------|
<one row per group row of the document, in document order>

Headline (host all, fresh, all): B without tool schemas <value>. <One table of the twelve bucket means for `fresh`/`all` per host and for host `all`.>

## Cut projections and verdicts

| Cut | Rule | Inputs | Projection (tokens per fresh boot) | Verdict | Built |
|-----|------|--------|------------------------------------|---------|-------|
| 1 | one task file per dispatch (D6) | A = <…>; <k> of <n> fresh boots in 6-7 | <…> | <keep or reject (…)> | <— or not built> |
| 2 | resume entry (D7) | s(0-5) = <…>, s(6-7) = <…> | <…> | <…> | <…> |
| 3 | support-file sections (D8) | share_A = <…>, share_D = <…> | <…> | <…> | <…> |
| 4 | sdd resume section (D9) | <…> | <…> (information) | reject (D9) | not built |
| 5 | re-read rule (D10) | mean rereads | <…> (information) | reject (D10) | not built |
```

- [ ] **Step 6: Verify**

Run:
```bash
bash -c 'set -e; f=.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
for s in "## Method" "## Baseline (two hosts)" "## Cut projections and verdicts"; do grep -qxF "$s" "$f"; done
for c in 1 2 3 4 5; do grep -qE "^\| $c \| .*\| (keep|reject \([^)]*\)) \| " "$f"; done
for a in AC1 AC2 AC3; do grep -qE "^\| $a \| " "$f"; done
if grep -qE "/private/|/var/folders/|launch-scope-|rel_[0-9a-f]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-" "$f"; then exit 1; fi
if grep -qE "<(the plan|AC[23].s|Step 2|one row|One table|…|—|T|12-char|sessions|entries|x|n|k|value|keep or)[^>]*>" "$f"; then exit 1; fi
if git status --porcelain | grep -vq "acceptance\.md$"; then exit 1; fi'
```
Expected: exit 0. It checks the sections, a verdict for every cut, the three AC rows, no private path or identifier, no unfilled skeleton slot (the Method block's `<window start>`/`<window end>` stay), and a worktree whose only change is the record.

- [ ] **Step 7: Commit, then clean up**

```bash
git add .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
git commit -m "docs(issue-448): two-host boot baseline and cut verdicts"
```

Then `rm -rf "$S"`, and confirm `test ! -e "$S"`.
