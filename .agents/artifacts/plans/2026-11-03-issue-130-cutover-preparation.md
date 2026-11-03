# Stage-4 Cutover Preparation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Commit the issue 130 cutover checklist `CL`, holding fresh read-only evidence for C1–C12 on every roster host and root. File one issue per red repair route, write the owner's gate, and stop before any activation.

**Architecture:** Tasks 1–4 are the evidence run. They run installed commands, git, `ls`, `readlink` and `ssh` against the fleet, and each adds its item sections to `CL`. Task 5 gives every red row a disposition through the tracker. Task 6 adds the summary, gate and criteria map and writes the acceptance record.

**Tech stack:** installed agent tools (`resolve-project`, `conformance`, `adopt-project`, `workflow-state`, `release`), `git`, `ssh`, `gh`, `nix eval`, and `python3 -I` for JSON reads and checks.

Spec: `.agents/artifacts/specs/2026-11-03-issue-130-cutover-preparation-design.md`. "§n" is its Decisions section *n*, and "Dn" a row of its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/130.

## Global Constraints

- The base is `fb8fd4f82395320581edd3160f4f93d789ce081f` (`origin/main`). The spec commits are `1f226906` and `61c6633b`, then the planning commits that append D14–D19.
- Only two files are written: `CL` = `.agents/artifacts/evidence/cutover-130-checklist.md` (Tasks 1–6) and `A` = `.agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md` (Task 6). Task 5 is the only tracker writer (D14).
- Never run `just switch`, `just gc`, `workflow-state migrate --apply`, `adopt-project verify --register`, a `release` verb other than `transaction status`, `agent-gate-bundle`, trials, a rollback, or any worktree add, remove or prune. Never write, fetch or pull in a roster root, nix-config's clone `/Users/anis/tmp/nix-config` included (D1, D15). Every git call into a roster root is `git --no-optional-locks -C R …`.
- `mbp` is this machine and runs commands directly. A remote host `H` runs `ssh -o BatchMode=yes -o ConnectTimeout=15 H -- <argv>`. An argv with quoted or glob arguments goes as a script on stdin: `ssh -o BatchMode=yes -o ConnectTimeout=15 H -- /bin/bash -s -- <args> < SCR/<name>.sh`. Task 1's `hostname` probe (C1.c) fixes each host's reachability. A host unreachable then is never probed again. Every one of its rows is `human-pending`, with Revision `—`, the UTC and Exit of that C1.c probe, and Observed `unreachable in Task 1 (C1.c exit <n>)`. A host that refuses later gets `human-pending` rows quoting the new ssh failure (D2, D15).
- Run every command over 30 s in the foreground, with an explicit timeout, as `launch-scope exec --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- <argv>`, using the ids your dispatch brief names. `SCR` is the directory `launch-scope scratch` (same flags) prints. Raw output stays under `SCR` and is never committed (D3). Shell state does not survive between Bash calls, so substitute `SCR` and recorded values as literals.
- Commit from the worktree root: `launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T<n>): <summary>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`. The subject is at most 64 bytes, and the commit is signed.
- Times are UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`), taken when a row's commands run.
- Item format in `CL` (§1, D4): the heading `### C<n> — <title>`, a `> ` line quoting the predicate and its source, a fenced `text` block with one `C<n>.<letter> <command>` line per command, the table `| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |`, and the line `Item verdict: **<worst row>**`, where red beats human-pending and human-pending beats green. Only C3 adds lines between them: its informational bundles, outside the table (D18).
- Rows: there is one row per (host, subject). A row may run several labelled commands, with `Exit` listing their exits in order (`0; 1`). `Subject` is `host`, a root path or an artifact path. `Revision` depends on the subject:
  - host: `system-<N>`;
  - root: the first 12 hex of `git --no-optional-locks -C R rev-parse HEAD`, then the branch (`symbolic-ref --short -q HEAD`, else `detached`), then `<n> dirty` (`status --porcelain` lines), run with the row;
  - artifact: the 12-hex commit read.
- `Observed` is a verbatim excerpt of the fields that decide the verdict, at most 160 characters, with `|` written `\|`. A longer list is counted there. `Verdict` is `green`, `red` or `human-pending`, read from the answer and never from the exit code. A command that cannot run (missing, crashed, or refusing in a way its rule does not name) makes its row red, with the failure as Observed.
- Caps on `CL`'s size after each task (D17): 10,240, 22,528, 30,720, 40,960, 44,032 and 57,344 bytes, for Tasks 1 to 6. `A` is capped at 10,240 bytes.
- The row check, which Tasks 1–4 run over their own items:

```bash
python3 -I - .agents/artifacts/evidence/cutover-130-checklist.md <<'EOF'
import os, re, sys
text = open(sys.argv[1], encoding="utf-8").read() + "\n## "
rank = {"green": 0, "human-pending": 1, "red": 2}
for item in os.environ["CHECK_ITEMS"].split():
    m = re.search(rf"^### {item} — .*?(?=^##)", text, re.M | re.S)
    assert m, item + ": no section"
    body = m.group(0)
    assert re.search(rf"^{item}\.[a-z] \S", body, re.M), item + ": no labelled command"
    rows = [r for r in body.splitlines() if r.startswith("| ") and not r.startswith("| Host |")]
    assert rows, item + ": no rows"
    seen = []
    for r in rows:
        c = [x.strip() for x in re.split(r"(?<!\\)\|", r.strip())[1:-1]]
        assert len(c) == 8, f"{item}: {len(c)} cells: {r[:60]}"
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", c[4]), f"{item}: UTC {c[4]}"
        assert re.fullmatch(r"\d+(; \d+)*", c[5]), f"{item}: exit {c[5]}"
        assert len(c[6]) <= 160 and c[7] in rank, f"{item}: cell 7 or 8: {r[:60]}"
        seen.append(c[7])
    worst = max(seen, key=rank.get)
    assert f"Item verdict: **{worst}**" in body, f"{item}: item verdict is not {worst}"
print("rows ok")
EOF
```

A task runs it in one Bash call after `export CHECK_ITEMS='<its item ids>'`, for example `export CHECK_ITEMS='C1 C12'`.

## Test seams

The spec's § Test seams, amended by D16; no test is added.
- The installed commands are run as an operator runs them.
- On the delivery worktree, `conformance run --purpose doctor` stays `passed`. `adopt-project verify` keeps the result and failed check ids it had before `CL` existed, and its candidate list names no `.md` (Tasks 1 and 6).
- Declared verification is `nix-build`, plus `agent-workflow-tests`, because `.agents/artifacts/evidence/*` is in its set. Both run at sdd's final gate.

## Delivery estimate and boundaries

- `all` (Tasks 1–6) is the only boundary: one branch and one docs-only PR (D13). One file's diff cannot be split across boundaries (D17).
- Tasks run in order. Task 5 files only from rows red as last observed (§6 item 5, D19).
- The issue 130 gate comment links `CL` at the merged commit (D13), so ship-issue's hold step posts it, not a task.

## Task index

Task 1 — Roster, host identity and the before-snapshot (C1, C12) — `.agents/artifacts/evidence/cutover-130-checklist.md` — full — [task-1.md](2026-11-03-issue-130-cutover-preparation.tasks/task-1.md)

Task 2 — Registration, conformance, host routes and the Codex handoff (C2, C8, C9, C10) — `.agents/artifacts/evidence/cutover-130-checklist.md` — full — [task-2.md](2026-11-03-issue-130-cutover-preparation.tasks/task-2.md)

Task 3 — Candidate, bundle and deprecated-path users (C3, C4, C11) — `.agents/artifacts/evidence/cutover-130-checklist.md` — full — [task-3.md](2026-11-03-issue-130-cutover-preparation.tasks/task-3.md)

Task 4 — Legacy release, ledgers and worktrees (C5, C6, C7) — `.agents/artifacts/evidence/cutover-130-checklist.md` — full — [task-4.md](2026-11-03-issue-130-cutover-preparation.tasks/task-4.md)

Task 5 — Dispositions and tracker filings — `.agents/artifacts/evidence/cutover-130-checklist.md` — full — [task-5.md](2026-11-03-issue-130-cutover-preparation.tasks/task-5.md)

Task 6 — Summary, gate, criteria map, after-snapshot and acceptance record — `.agents/artifacts/evidence/cutover-130-checklist.md`, `.agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md` — full — [task-6.md](2026-11-03-issue-130-cutover-preparation.tasks/task-6.md)

## Acceptance map

AC1–AC5 are the issue's `## Acceptance criteria` lines, and AC6–AC10 its `### Additional acceptance criteria`, in order (§6). Task 6 writes every row of `A`, and sdd's final review owns the verdicts. A row is `met` only when all its mapped items are green, `human_pending` when the rest wait on the owner, and otherwise `unmet`. In an evidence row, the `awk` verdict read prints `<item> **<verdict>**` per named item. The evidence conditions are: `CL` at the D19 commit, each item over every host reachable in Task 1 and its roots, and `origin/main` as in `CL`'s `Revisions:` line. Task 6 copies the commands and threshold into `A`'s `Check or command`, and the conditions into `Conditions`.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 6 | `awk -v want='C2 C3 C5 C6 C8 C10' '/^### C[0-9]+ — /{i=$2} /^Item verdict: / && index(" " want " ", " " i " "){print i, $3}' .agents/artifacts/evidence/cutover-130-checklist.md`; conditions: the evidence conditions; threshold: `met` when it prints 6 lines, all ending `**green**`; `unmet` when any ends `**red**` or fewer than 6 print; otherwise `human_pending` |
| AC2 | human (classified) | Task 6 | P1 after activation: the owner judges F1's ladder-absence check and a closed `error.code` from `resolve-project resolve` on a contract-less scratch repository |
| AC3 | human (classified) | Task 6 | P2: the owner runs gate step 6 once per host, then re-reads C12 |
| AC4 | human (classified) | Task 6 | P3: the owner's Claude-driven and Codex-driven ships on the strict path (merged PR, closed issue, run outcome) |
| AC5 | human (classified) | Task 6 | P6: the owner appends the retirement section to `CL` |
| AC6 | evidence (classified) | Task 1 | `awk -v want='C1' '/^### C[0-9]+ — /{i=$2} /^Item verdict: / && index(" " want " ", " " i " "){print i, $3}' .agents/artifacts/evidence/cutover-130-checklist.md` and `grep -c 'Arcwave is in' .agents/artifacts/evidence/cutover-130-checklist.md`; conditions: the evidence conditions; threshold: `met` when they print `C1 **green**` and a count of 1 or more; `human_pending` when `C1 **human-pending**` (an unreachable host) and a count of 1 or more; otherwise `unmet` |
| AC7 | evidence (classified) | Task 4 | `awk -v want='C6 C7' '/^### C[0-9]+ — /{i=$2} /^Item verdict: / && index(" " want " ", " " i " "){print i, $3}' .agents/artifacts/evidence/cutover-130-checklist.md`; conditions: the evidence conditions; threshold: `met` when it prints 2 lines, both ending `**green**`; `unmet` when any ends `**red**` or fewer than 2 print; otherwise `human_pending` (`migrate` only, cleared by gate step 1) |
| AC8 | human (classified) | Task 6 | P2, exercised before P6 is recorded; the owner |
| AC9 | human (classified) | Task 6 | Task 2's C9 rows, plus P3's owner-run sessions judged against the installed declaration |
| AC10 | human (classified) | Task 6 | P5: the owner's merge, issue close and cleanup reconciliation, before retirement |

## Decisions

- Scope and authority: D1, D13 and D14 (every task). Format and freshness: D3, D4, D5 and D17. No tooling: D6.
- Roster: D2 and D15 (Task 1). C2 and C10: D15 and D16; C8 and C9: D10 (Task 2). C3 and C4: D11 and D18; C11: D8 (Task 3). C5–C7: D9 and D15 (Task 4).
- Dispositions: D7, D8, D14, D16 and D19 (Task 5). Gate: D12; delivery: D13; citations: D19 (Task 6). Planning appended D14–D17; plan review D18–D19.

## Standards review provenance

- Reviewer: Codex (gpt-6-astra, effort xhigh), via `codex-companion task --fresh --reviewer plan-review`, isolated and read-only, at base `fb8fd4f82395320581edd3160f4f93d789ce081f`; focus: none.
- Findings: accepted 4, rejected 0, deferred 0. B1: a failed C7 worktree inventory is red, never green (Tasks 4 and 5). B2: the AC1, AC6 and AC7 map rows carry commands, conditions and thresholds. B3: D18. S1: D19.
- Discussion D1: the reviewer could not reach api.github.com and used the supplied issue text; no fallback reviewer ran.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"4c44bf23cc53e0c5ae03da13c82542c39ab456dd","kind":"git-range-ownership/v1","process_ranges":[{"base":"fb8fd4f82395320581edd3160f4f93d789ce081f","boundaries":["all"],"head":"cfd3ad5b7e64f999b372bae34b14e4b8a80c03d8"}],"tree":"d0549c22a9ae2a8eb52bb4651a0d530865c56b0d"},"boundaries":[{"acceptance":"Every task of the plan is complete and the declared verification passes","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5","t6"],"process_package":{"plan":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.md","spec":".agents/artifacts/specs/2026-11-03-issue-130-cutover-preparation-design.md","tasks":[".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-1.md",".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-2.md",".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-3.md",".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-4.md",".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-5.md",".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-6.md"]},"tasks":[1,2,3,4,5,6]}],"delivery_base":"fb8fd4f82395320581edd3160f4f93d789ce081f","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":418,"boundary":"all","deleted_lines":0,"record_bytes":47991,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":6,"owner":0,"path":".agents/artifacts/specs/2026-11-03-issue-130-cutover-preparation-design.md"},{"bounds":[{"added_lines":204,"boundary":"all","deleted_lines":0,"record_bytes":22822,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.md"},{"bounds":[{"added_lines":222,"boundary":"all","deleted_lines":0,"record_bytes":18033,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-1.md"},{"bounds":[{"added_lines":206,"boundary":"all","deleted_lines":0,"record_bytes":15666,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-2.md"},{"bounds":[{"added_lines":196,"boundary":"all","deleted_lines":0,"record_bytes":15730,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-3.md"},{"bounds":[{"added_lines":231,"boundary":"all","deleted_lines":0,"record_bytes":15293,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-4.md"},{"bounds":[{"added_lines":229,"boundary":"all","deleted_lines":0,"record_bytes":18533,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-5.md"},{"bounds":[{"added_lines":255,"boundary":"all","deleted_lines":0,"record_bytes":20116,"support":{"covers":["t6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.tasks/task-6.md"}],"proposed_boundary":"all","schema_version":3}
```
