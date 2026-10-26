# Acceptance record — issue 448

Baseline taken on host mbp from the `mbp` root (`~/.claude/projects`) and a read-only copy of `anis-desktop`'s (https://github.com/fagenorn/nix-config/issues/448); each row's Commit is the head its evidence was taken on.

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] `just agent-costs --report boot` reports per-owner and mean boot buckets. Measured by: unit tests on fixture transcripts. | code | `tests/test_agent_boot_report.py`, run by `just agent-workflow-tests`. `BootReportTest` (Task 1) checks the per-owner rows: the bucket sum equals B, the call-0 split at 2.44, read-backs, re-reads, resume content, skill sub-maps, cohorts, `unsplit`, refused flags and the text sections, plus the mean rows. `HostsTest` (Task 2) adds per-host and pooled means over two labelled roots. | in final verification (`just agent-workflow-tests` runs `tests/test_agent_boot_report.py`: `BootReportTest`, `HostsTest`) | 8b8d869ba822 | host mbp; the SDD ledger's Final verification line names the head and tree | — |
| AC2 | [code] Kept cuts are pinned by contract tests. `just agent-workflow-tests`, `just agent-instruction-budget` (no raise label) and `just build` pass. | code | `SlimBootContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: one test group per cut that Tasks 4–6 built, named in the record's cut rows. Also `just agent-instruction-budget` with no `--raise-label` (Task 7 runs it and fills row `AC2`), and `just agent-workflow-tests` and `just build`, which sdd's final gate runs on the final head. | built cuts and their `SlimBootContractsTest` tests: cut 1 at 1efe9236adaf (`test_phase_6_hands_sdd_the_reviewed_token_and_sdd_skips_the_package_read`); cut 2 at 755a14c9a6e0, entry fix at 314fe8dcba41 (`test_pack_carrying_prompts_name_the_resume_entry`, `test_the_entry_runs_its_checks_before_any_skill_section`); cut 3 at f0dacef80053, pin reordered at 8b8d869ba822 (`test_every_section_and_file_the_verified_pack_reads_exists`, `test_phases_6_7_read_neither_the_stop_rules_nor_the_ship_handoff`). Not built: cut 4 (reject, D9) and cut 5 (reject, D10). Skill contract tests: 232 tests OK (skipped=3). `just agent-instruction-budget` (no `--raise-label`) `check: pass` at 8b8d869ba822, 2026-10-26T14:28:44Z. `just agent-workflow-tests` and `just build`: in final verification | 8b8d869ba822 | host mbp; the SDD ledger's Final verification line names the head and tree | — |
| AC3 | [evidence] The mean fresh-owner boot, excluding tool schemas, falls by at least 25k against the 2026-10-26 baseline on new owner transcripts. The replay sweep is re-run, and its chosen threshold is stated with reasons. | evidence | **Before merge:** Task 3's two-host baseline. The window is 2026-10-24T00:00:00Z → record time, from roots `mbp` and an `anis-desktop` scratch copy, with host-`all`, `fresh`, phase-group-`all` B without tool schemas, each host's figure and every stratum count. Task 7 adds one `just agent-costs --report owners --sweep` per host root over 2026-10-24T00:00:00Z → its record time, with each chosen threshold stated with reasons (D13, D19). **Held** (issue kept open as `needs-verification`, D12): `--report boot` over the window from the later host's first post-merge `just switch`. The window closes once every baseline host × phase-group stratum has 5 or more `fresh` boots, 20 or more in all. Met when the baseline combined mean of B without tool schemas, minus the post-deploy stratum means reweighted to the baseline's host × phase-group mix, is at least **25,000**; each host's fall is reported alongside. Then the per-host post-deploy sweeps. Row `AC3` of the acceptance record. | before merge: § Baseline (headline 78,499) and § Pre-merge sweep (mbp: threshold=200000; anis-desktop: threshold=170000, which does not keep against 200,000; 200,000 stands); the fall is not measurable before deploy and is held per § Post-deploy protocol | 8b8d869ba822 | hosts mbp and anis-desktop (read-only copy of 12 sessions/22 entries); baseline window 2026-10-24T00:00:00Z → 2026-10-26T10:54:35Z; sweep window 2026-10-24T00:00:00Z → 2026-10-26T14:27:13Z; T = 2026-10-26T14:27:13Z | — |

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
| 1 | one task file per dispatch (D6) | A = 8,630 (medians 8,948 B over 134 plans and 12,108 B over 546 task files, ÷ 2.44, at ca6ba1ae); 79 of 103 fresh boots in 6-7 | 8,808 | keep | built at 1efe9236adaf; net -8 bytes |
| 2 | resume entry (D7) | s(0-5) = 0.3400, s(6-7) = 0.2728 | 3,119 | keep | built at 755a14c9a6e0; net -69 bytes |
| 3 | support-file sections (D8) | share_A = 0.3690, share_D = 0.1289; 79 of 103 fresh boots in 6-7 | 1,559 | keep | built at f0dacef80053; net -9 bytes |
| 4 | sdd resume section (D9) | the two gate sections are 0.1059 of sdd/SKILL.md; 79 of 103 fresh boots in 6-7 | 616 (information) | reject (D9) | not built |
| 5 | re-read rule (D10) | mean rereads over 103 fresh boots | 690 (information) | reject (D10) | not built |

## Pre-merge sweep

One `--report owners --sweep` per host root, over 2026-10-24T00:00:00Z → T = 2026-10-26T14:27:13Z, from head 8b8d869ba822. `$S` is the Method's scratch directory, `T` the UTC second the sweeps were run, and `<label>` and `<root>` one of the two host pairs (`mbp`, `$HOME/.claude/projects`) and (`anis-desktop`, `$S/anis-desktop/projects`). Run from the worktree root, JSON for the figures and the same command without `--format json` for the text twin:

```bash
T="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_costs --report owners --sweep --format json \
  --events-since 2026-10-24T00:00:00Z --events-before "$T" --projects-dir "<root>" > "$S/sweep-<label>.json"
jq '.calibration.identity_matches' "$S/sweep-<label>.json"
jq '.lineages | length' "$S/sweep-<label>.json"
jq -c '.simulated[] | select(.step == "threshold") | [.spec, .dollars_per_delivered, .mean_saving, .lower_bound, .verdict]' "$S/sweep-<label>.json"
```

The sweep compares its threshold singles against the replay's pre-issue-432 origin (110,000) and its phase grid against the chosen single, so no sweep row says whether an arm beats the live 200,000. `pair200.py` does: it collects the host's lineages as the sweep does, fits the boot model, and replays two arms that hold every non-threshold choice equal, the sweep's final spec and the same spec with its threshold item(s) replaced by `threshold=200000`. It prints the saving of the first against the second, as mean, lower bound and keep. It is run per host whose threshold step chose an arm other than `threshold=200000`:

```bash
SPEC="$(jq -r '[.simulated[] | select(.step == "final")] | last | .spec' "$S/sweep-<label>.json")"
PYTHONPATH="$PWD/python" python3 "$S/scripts/pair200.py" "<root>" 2026-10-24T00:00:00Z "$T" "$SPEC"
```

`pair200.py`:

```python
"""Pair a host's chosen sweep arm against the same arm with threshold=200000.

usage: PYTHONPATH="$PWD/python" python3 pair200.py ROOT SINCE BEFORE SPEC
ROOT is the host's projects directory, SINCE and BEFORE are the sweep's RFC 3339
event bounds, SPEC is the chosen spec (the sweep's last `final` row). Both arms hold
every non-threshold choice equal; the second replaces the threshold item(s) with
threshold=200000.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from agent_tools import agent_owner_replay, agent_owner_report
from agent_tools.agent_costs import parse_rfc3339_utc


def main(root, since, before, spec):
    start, end = parse_rfc3339_utc(since), parse_rfc3339_utc(before)
    lineages, _ = agent_owner_report.collect(
        Path(root), cutoff=start.timestamp(), since=start, before=end,
        eval_rows=None, executor_factory=ProcessPoolExecutor)
    model = agent_owner_replay.fit(lineages)
    items = spec.split(",")
    first = next(i for i, item in enumerate(items) if item.startswith("threshold"))
    rest = [item for item in items if not item.startswith("threshold")]
    held = ",".join(rest[:first] + ["threshold=200000"] + rest[first:])
    chosen = agent_owner_replay.parse_arm(f"chosen={spec}")
    live = agent_owner_replay.parse_arm(f"live={held}")
    verdict = agent_owner_replay._Evaluation(lineages, model).verdict(live, chosen)
    print(f"lineages={len(lineages)} chosen={spec} against={held}")
    print(f"mean_saving={verdict.mean:.4f} lower_bound={verdict.lower_bound:.4f} keep={verdict.keep}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
```

### mbp

Window events 2026-10-24T00:00:00Z → 2026-10-26T14:27:13Z; 49 lineages; identity check true (`calibration.identity_matches`).

| Threshold arm | $ per delivered issue | Mean saving | Lower bound | Verdict |
|---------------|-----------------------|-------------|-------------|---------|
| threshold=90000 | 155.35 | -25.19 | -28.52 | not chosen |
| threshold=110000 | 101.68 | 0.00 | 0.00 | not chosen |
| threshold=140000 | 94.45 | 3.39 | 3.01 | not chosen |
| threshold=170000 | 92.67 | 4.23 | 3.80 | not chosen |
| threshold=200000 | 92.61 | 4.26 | 3.86 | chosen |
| threshold=never | 92.95 | 4.10 | 3.70 | info |

Mean saving and lower bound are dollars per lineage against the 110,000 reference. Chosen arm: `threshold=200000`, the live value. Paired verdict against 200,000: chosen arm is 200,000. Reason: it is the cheapest single, 0.07 dollars per delivered issue under 170,000, and no lower arm keeps against it.

### anis-desktop

Window events 2026-10-24T00:00:00Z → 2026-10-26T14:27:13Z, read-only copy of 12 sessions/22 entries; 23 lineages; identity check true (`calibration.identity_matches`).

| Threshold arm | $ per delivered issue | Mean saving | Lower bound | Verdict |
|---------------|-----------------------|-------------|-------------|---------|
| threshold=90000 | 129.34 | -8.74 | -11.35 | not chosen |
| threshold=110000 | 107.00 | 0.00 | 0.00 | not chosen |
| threshold=140000 | 98.13 | 3.47 | 2.85 | not chosen |
| threshold=170000 | 95.86 | 4.36 | 3.65 | chosen |
| threshold=200000 | 96.21 | 4.23 | 3.53 | not chosen |
| threshold=never | 98.22 | 3.44 | 2.70 | info |

Mean saving and lower bound are dollars per lineage against the 110,000 reference. Chosen arm: `threshold=170000`, with the sweep's final spec `threshold=170000,help=drop`. Paired verdict against 200,000 (`threshold=170000,help=drop` against `threshold=200000,help=drop`, `pair200.py`): mean saving 0.1297, lower bound -0.0583, keep false. Reason: 170,000 is 0.34 dollars per delivered issue under 200,000, but the paired lower bound is below zero, so the sweep cannot tell it from 200,000 on 23 lineages.

### Threshold statement

The threshold stays 200,000 in this PR: the observed boots are not yet cut, and D13 lowers it only in a follow-up commit citing issue 448, after both hosts' post-deploy sweeps choose a lower arm against 200,000. Today mbp's sweep chooses 200,000 itself, and anis-desktop's chooses 170,000 but its paired verdict against 200,000 is not a keep. Both identity checks are true, so the replay reproduces the observed spend on both hosts. `phase_budget`'s 200,000 default is not touched here.

## Post-deploy protocol

Held (D12): none of this runs before merge, so the issue ships as `needs-verification`. A later session follows these steps without the plan.

1. **Window start `W`.** A generation activated after the merge can still be built from an older checkout (`just switch` builds the current checkout's flake), so time alone does not prove deployment. On each host `h`, list the system generations with their activation times (`darwin-rebuild --list-generations` on mbp; `ssh anis-desktop 'wsl -e bash -l -c "nixos-rebuild list-generations"'` on anis-desktop) and, newest first, find the earliest generation whose closure installs the merged skills: its `-home-manager-files` store path (`nix-store --query --requisites <generation link> | grep -- '-home-manager-files$'`) contains, for every built cut, each `SlimBootContractsTest` pin at the merge commit in the installed copy of the file that test reads (`.claude/skills/<skill>/<file>`, for example `from-issue/resume-pack.md`, `sdd/SKILL.md`, `orchestrate-issues/SKILL.md`), matched after collapsing whitespace as the tests do. `W_h` is that generation's activation time. Record per host the generation number, `W_h` and the matched store path. A host with no such generation has not deployed: record nothing and run again later. `W` is the later of the `W_h`, as RFC 3339 UTC.
2. **Copy and measure.** Copy anis-desktop with § Method's scripts and commands, passing `W` as the window start. Then run `just agent-costs --report boot --format json --events-since W --events-before <now> --projects-dir "mbp=$HOME/.claude/projects" --projects-dir "anis-desktop=<copy>" --top 100000`.
3. **Close rule.** Every host × phase-group stratum that holds a `fresh` boot in § Baseline must hold 5 or more `fresh` boots in the window, and the window 20 or more in all. Otherwise record nothing and run again later.
4. **Weights.** Copy from § Baseline, for each such stratum `(h, g)`, the count `n0(h, g)` and the mean B without tool schemas `m0(h, g)`. Add `N0 = Σ n0` and the headline `M0` (host `all`, `fresh`, `all`: 78,499).
5. **Verdict.**
   - `M1 = Σ n0(h, g) / N0 × m1(h, g)`, where `m1` is the window's mean B without tool schemas for the same stratum.
   - **Met when `M0 − M1 ≥ 25,000`.**
   - Each host's fall, `M0(h) − Σ_g n0(h, g) / N0(h) × m1(h, g)`, is reported alongside for information.
6. **Sweeps.** Run § Pre-merge sweep's command per host over `[W, now]`, and `pair200.py` for each host whose threshold step chose an arm other than `threshold=200000` (a final spec with no threshold item kept the 110,000 reference: pass `threshold=110000,<spec>`). A lower threshold is set only when both hosts' pairs, re-run over `[W, now]`, keep it against 200,000, in a follow-up commit citing issue 448 (D13).
7. **Record.** Fill row `AC3`'s evidence columns and its verdict. On `met`, close the issue; otherwise keep it held.
