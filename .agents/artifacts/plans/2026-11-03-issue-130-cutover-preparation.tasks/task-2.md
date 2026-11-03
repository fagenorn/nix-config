# Task 2: Registration, conformance, host routes and the Codex handoff

This task covers the spec §3 rows C2, C8, C9 and C10, and follows D10, D15 and D16. It adds four item sections to `CL`. They feed AC1's and AC9's checks.

**Files:**
- Modify: `.agents/artifacts/evidence/cutover-130-checklist.md` (`CL`)

**Interfaces:**
- Consumes: Task 1's `## Roster`, meaning its (host, project_id, root) rows and each host's reachability.
- Produces: `### C2 — Registered, compatible and adoption current`, `### C8 — Codex ship handoff installed`, `### C9 — Host routes answer as declared` and `### C10 — Doctor clean on every adopted host`. They sit in `## Evidence` in numeric order, between C1 and C12.

**Invariants:**
- The task is read-only, per Global Constraints, and `CL` is its only write. Sections and rows written by Task 1 keep their bytes.
- Every roster root on a reachable host has exactly one C2 row and one C10 row. Every reachable host has one C2 host row, one C8 row and one C9 row. An unreachable host has one `human-pending` row in each item.
- The answer decides the verdict, never the exit code (D4). Plain `verify` exits 0 on `not_conformant`. Its `registered` field is `false` unless that call registered, so it is never read as registration. Registration is the C2.a fleet row.

- [ ] **Step 1: Confirm red**

Run: `grep -c '^### C2 — ' .agents/artifacts/evidence/cutover-130-checklist.md`. Expected: `0`, exit 1.

- [ ] **Step 2: C2**

```text
C2.a resolve-project platform-status --fleet
C2.b conformance run --purpose fleet --repo-root R
C2.c adopt-project verify --repo-root R
```

- Run C2.a once per reachable host (timeout 120 s), saving it to `SCR/<H>/fleet-status.json`. The host row reads each `fleet[]` row's `project_id`, `compatible`, `platform_interval` and `reason_code`, and `platform.platform_version`. It is red when any row has `compatible` other than `true`, or when a roster root on that host has no `fleet[]` row. Otherwise it is green. Observed names the version, the compatible count over the row count, and the interval.
- Run C2.b and C2.c per root (timeout 300 s each), saving to `SCR/<H>/<project>-fleet.json` and `SCR/<H>/<project>-verify.json`. Per D15, `fleet` runs once per root, because its checks are repository checks on the `--repo-root` subject.
- A root row is red when C2.b's `outcome.status` is not `passed`; Observed then gives `outcome.primary_check_id` and `repairs[].repair_id`. It is also red when C2.c's `result` is `not_conformant`; Observed then names the failed check ids.
- `adopted` is green. `adopted_with_blockers` is green, with its `blockers` listed in Observed.
- Planning saw nix-config's verify as `not_conformant` on `adoption-evidence-record` (D16) and Nodo's fleet run failing `repository.ignore.runtime_sentinel`. Record whatever this run observes.

- [ ] **Step 3: C10**

```text
C10.a conformance run --purpose doctor --repo-root R
```

Run per root (timeout 300 s), saving to `SCR/<H>/<project>-doctor.json`.
- `outcome.status` `passed` is green, with any `warning` checks listed by id.
- `failed` is red. Observed gives `outcome.primary_check_id`, each `repairs[].repair_id`, and the count of checks whose status is `suppressed` or `not_run`.
- `incomplete` is rerun once. A repeat is red with the incomplete check id.

The row also records `host.admission.declaration`'s status for C9.

- [ ] **Step 4: C8**

```text
C8.a ls -lL .agents/skills/ship-issue/HUMAN-GATE.md
C8.b grep -n HUMAN-GATE.md .agents/skills/ship-issue/SKILL.md
C8.c git log -1 --format=%H -- home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md
```

- Run C8.a and C8.b per reachable host from its home directory (locally with `~/` prefixed), timeout 60 s. A host row is green when C8.a lists a regular file and C8.b prints at least one line. It is red otherwise.
- Run C8.c once, in the delivery worktree. It is one row: host `mbp`, subject `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`, revision the worktree's 12-hex `HEAD`. It is green when it prints a commit. Its Observed gives that commit (issue 119, PR 141).

- [ ] **Step 5: C9**

```text
C9.a workflow-state host-route --route claude-code
C9.b workflow-state host-route --route codex
```

Run both per reachable host (timeout 60 s). The host row is green when all of these hold:
- C9.a answers `support` `supported` with a positive `agent_slots`;
- C9.b answers `support` `unsupported`, `reason_code` `declared_unsupported` and `alternative` `/from-issue <issue> --auto`;
- every C10 row on that host has `host.admission.declaration` `passed`.

It is red on `reason_code` `declaration_missing`, `declaration_invalid` or `route_undeclared`, or when that check is not `passed`. Codex's `unsupported` is the declared answer and is not red (D10). Observed gives both answers, for example `claude-code supported 7; codex unsupported declared_unsupported`.

- [ ] **Step 6: Write the sections**

Insert the four sections into `CL` after C1's section, in the order C2, C8, C9, C10, each in the Global Constraints item format. The `> ` lines are:
- C2: the issue's "every fleet project … is registered and compatible", plus #71's "per-project adoption evidence current";
- C8: "the Codex ship handoff is in place so that removing the fallback ladders does not strand a Codex session at the shipping step";
- C9: the refresh's "Claude and Codex paths complete against declared host capabilities, including bounded capacity admission";
- C10: "`doctor` is clean on every adopted host".

- [ ] **Step 7: Verify**

```bash
set -e
CL=.agents/artifacts/evidence/cutover-130-checklist.md
test "$(wc -c < "$CL")" -le 22528
test "$(grep -n '^### C' "$CL" | cut -d' ' -f2 | tr '\n' ' ')" = 'C1 C2 C8 C9 C10 C12 '
python3 -I - "$CL" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read() + "\n## "
roster = text.split("### Projects", 1)[1].split("\n## ", 1)[0]
rows = [[x.strip() for x in c.strip().strip("|").split("|")] for c in roster.splitlines()
        if c.startswith("| ") and not c.startswith("| Host |")]
for item in ("C2", "C10"):
    body = re.search(rf"^### {item} — .*?(?=^##)", text, re.M | re.S).group(0)
    for cells in rows:
        assert f"| {cells[0]} | {cells[2]} |" in body, f"{item}: no row for {cells[0]} {cells[2]}"
print("coverage ok")
EOF
```

Then, in one Bash call, run `export CHECK_ITEMS='C2 C8 C9 C10'` followed by the root's row check.
Expected: `coverage ok`, then `rows ok`. Before Step 6 the heading-order test fails.

- [ ] **Step 8: Commit**

```bash
git add .agents/artifacts/evidence/cutover-130-checklist.md
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T2): registration, doctor, routes, Codex handoff" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Verify: `git status --short -- .agents/artifacts/evidence` prints nothing.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":175,"boundary":"all","deleted_lines":0,"record_bytes":24960,"support":{"covers":["r1-1","r2-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2-1","last_task":6,"owner":2,"path":".agents/artifacts/evidence/cutover-130-checklist.md"}]}}
```
