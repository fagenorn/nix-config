# Acceptance record — issue 448

Baseline taken on host mbp from the `mbp` root (`~/.claude/projects`) and a read-only copy of `anis-desktop`'s (https://github.com/fagenorn/nix-config/issues/448); each row's Commit is the head its evidence was taken on.

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] `just agent-costs --report boot` reports per-owner and mean boot buckets. Measured by: unit tests on fixture transcripts. | code | `tests/test_agent_boot_report.py`, run by `just agent-workflow-tests`. `BootReportTest` (Task 1) checks the per-owner rows: the bucket sum equals B, the call-0 split at 2.44, read-backs, re-reads, resume content, skill sub-maps, cohorts, `unsplit`, refused flags and the text sections, plus the mean rows. `HostsTest` (Task 2) adds per-host and pooled means over two labelled roots. | — | — | — | — |
| AC2 | [code] Kept cuts are pinned by contract tests. `just agent-workflow-tests`, `just agent-instruction-budget` (no raise label) and `just build` pass. | code | `SlimBootContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: one test group per cut that Tasks 4–6 built, named in the record's cut rows. Also `just agent-instruction-budget` with no `--raise-label` (Task 7 runs it and fills row `AC2`), and `just agent-workflow-tests` and `just build`, which sdd's final gate runs on the final head. | — | — | — | — |
| AC3 | [evidence] The mean fresh-owner boot, excluding tool schemas, falls by at least 25k against the 2026-10-26 baseline on new owner transcripts. The replay sweep is re-run, and its chosen threshold is stated with reasons. | evidence | **Before merge:** Task 3's two-host baseline. The window is 2026-10-24T00:00:00Z → record time, from roots `mbp` and an `anis-desktop` scratch copy, with host-`all`, `fresh`, phase-group-`all` B without tool schemas, each host's figure and every stratum count. Task 7 adds one `just agent-costs --report owners --sweep` per host root over 2026-10-24T00:00:00Z → its record time, with each chosen threshold stated with reasons (D13, D19). **Held** (issue kept open as `needs-verification`, D12): `--report boot` over the window from the later host's first post-merge `just switch`. The window closes once every baseline host × phase-group stratum has 5 or more `fresh` boots, 20 or more in all. Met when the baseline combined mean of B without tool schemas, minus the post-deploy stratum means reweighted to the baseline's host × phase-group mix, is at least **25,000**; each host's fall is reported alongside. Then the per-host post-deploy sweeps. Row `AC3` of the acceptance record. | — | — | — | — |

## Method

Run on mbp from the worktree root. `$S` is a scratch directory that is removed once the record is committed. The first script runs in anis-desktop's WSL login shell and prints a marked, base64-encoded tarball of the owner sessions modified since the window start; the second verifies its sha256 and unpacks it.

`select-sessions.sh`:

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

`extract.py`:

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

Transfer, then unpack with the sha256 that the transfer's last stderr line prints:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=30 anis-desktop "wsl -e bash -l -s 2026-10-24T00:00:00Z" < "$S/scripts/select-sessions.sh" > "$S/anis-desktop.b64" 2> "$S/anis-desktop.err"
tail -1 "$S/anis-desktop.err"   # prints sessions=N entries=N bytes=N sha256=HEX64
python3 -I "$S/scripts/extract.py" "$S/anis-desktop.b64" <sha256 printed> "$S/anis-desktop/projects"
```

The report, JSON for the figures and text for reading, with the window closed at the UTC second it is run:

```bash
PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_costs --report boot --format json \
  --events-since <window start> --events-before <window end> \
  --projects-dir "mbp=$HOME/.claude/projects" --projects-dir "anis-desktop=$S/anis-desktop/projects" \
  --top 100000 > "$S/baseline.json"
```

The projections below read that JSON and the skill documents through `git show ca6ba1ae:<path>`; each is a sum over the fresh boots divided by their count, in tokens.

## Baseline (two hosts)

Window 2026-10-24T00:00:00Z → 2026-10-26T10:54:35Z; head 661ea6c42e91; 11 sessions/20 entries copied from anis-desktop; observed characters per token 2.47; unsplit: mbp 0, anis-desktop 0.

| Host | Cohort | Phase group | Boots | B mean | B without tool schemas |
|------|--------|-------------|-------|--------|------------------------|
| mbp | fresh | 0-5 | 16 | 75,627 | 61,454 |
| mbp | fresh | 6-7 | 54 | 99,509 | 83,057 |
| mbp | fresh | all | 70 | 94,050 | 78,119 |
| mbp | spawned | 0-5 | 35 | 87,513 | 70,765 |
| mbp | spawned | all | 35 | 87,513 | 70,765 |
| anis-desktop | fresh | 0-5 | 8 | 89,541 | 71,355 |
| anis-desktop | fresh | 6-7 | 25 | 99,834 | 81,847 |
| anis-desktop | fresh | all | 33 | 97,339 | 79,303 |
| anis-desktop | spawned | 0-5 | 15 | 101,791 | 83,805 |
| anis-desktop | spawned | all | 15 | 101,791 | 83,805 |
| all | fresh | 0-5 | 24 | 80,265 | 64,754 |
| all | fresh | 6-7 | 79 | 99,612 | 82,674 |
| all | fresh | all | 103 | 95,104 | 78,499 |
| all | spawned | 0-5 | 50 | 91,796 | 74,677 |
| all | spawned | all | 50 | 91,796 | 74,677 |

Headline (host all, fresh, all): B without tool schemas 78,499. Mean bucket tokens per fresh boot, phase group all:

| Bucket | mbp | anis-desktop | all |
|--------|-----|--------------|-----|
| tool_schemas | 15,931 | 18,035 | 16,605 |
| harness | 15,741 | 20,958 | 17,413 |
| prompt | 2,353 | 3,456 | 2,706 |
| skill_bodies | 16,873 | 17,268 | 17,000 |
| skill_files | 7,859 | 7,181 | 7,642 |
| plan_reads | 14,123 | 16,120 | 14,763 |
| resume_reads | 2,759 | 758 | 2,118 |
| rereads | 875 | 300 | 690 |
| other_reads | 5,215 | 3,285 | 4,597 |
| commands | 5,376 | 2,839 | 4,563 |
| assistant | 6,945 | 7,137 | 7,006 |
| unexplained | 0 | 0 | 0 |
| B | 94,050 | 97,339 | 95,104 |
| B without tool schemas | 78,119 | 79,303 | 78,499 |
## Cut projections and verdicts

A cut is kept when its projection is at least 1,000 tokens per fresh boot (D16); cuts 4 and 5 are information only.

| Cut | Rule | Inputs | Projection (tokens per fresh boot) | Verdict | Built |
|-----|------|--------|------------------------------------|---------|-------|
| 1 | one task file per dispatch (D6) | A = 8,630 (medians 8,948 B over 134 plans and 12,108 B over 546 task files, ÷ 2.44, at ca6ba1ae); 79 of 103 fresh boots in 6-7 | 8,808 | keep | built; net -8 bytes |
| 2 | resume entry (D7) | s(0-5) = 0.3400, s(6-7) = 0.2728 | 3,119 | keep | built; net -69 bytes |
| 3 | support-file sections (D8) | share_A = 0.3690, share_D = 0.1289; 79 of 103 fresh boots in 6-7 | 1,559 | keep | built; net -9 bytes |
| 4 | sdd resume section (D9) | the two gate sections are 0.1059 of sdd/SKILL.md; 79 of 103 fresh boots in 6-7 | 616 (information) | reject (D9) | not built |
| 5 | re-read rule (D10) | mean rereads over 103 fresh boots | 690 (information) | reject (D10) | not built |
