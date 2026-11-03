# Task 6: Summary, gate, criteria map, after-snapshot and acceptance record

This task covers spec §1 (summary, readiness, criteria map), §5 and §6, and follows D12 and D13. It closes the evidence run with the after-snapshot, completes `CL`, and writes `A` for AC1–AC10. The gate text is the owner's activation and rollback procedure, so every bound value must be one this run observed.

**Files:**
- Modify: `.agents/artifacts/evidence/cutover-130-checklist.md` (`CL`)
- Create: `.agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md` (`A`)

**Interfaces:**
- Consumes:
  - Task 1's header, its `### Hosts` columns (`Reachable`, `Generation`, `K_H`), its `### Projects` rows and `HEAD before`, and its `SCR/rev.sh` text, repeated in Step 2;
  - the item verdicts of C1–C12;
  - Task 5's `## Dispositions`;
  - the issue body (`gh issue view 130 --repo fagenorn/nix-config --json body --jq .body`).
- Produces in `CL`:
  - after the `Hosts:` line, the lines `Evidence window: <earliest row UTC> to <latest row UTC>` and `Activation readiness: …`;
  - `## Summary` before `## Roster`;
  - the roster's `Registry sha256 after` and `HEAD after` columns, plus a `Snapshot:` paragraph;
  - `### P1–P6 — Post-activation items`, closing `## Evidence`;
  - `## Human gate` and `## Criteria map` after `## Dispositions`.
- Produces `A`, the sdd acceptance record.

**Invariants:**
- The task is read-only toward the fleet, per Global Constraints. Rows of C1–C12 keep their bytes.
- Each Summary verdict equals its section's item verdict. P1–P6 are `post` and `human-pending`. The readiness line reads `Activation readiness: activation not permitted — <r> red, <h> human-pending, <g> green of 12 pre-activation items.` whenever any of C1–C12 is not green. When all are green, it reads `Activation readiness: all 12 pre-activation items green; the owner may run the gate from step 1.`
- The gate's only placeholder is `<candidate>`. Each reachable host's `K_H` and `N_H`, and each roster root, are bound literally. An unreachable host keeps the names `K_H` and `N_H` under the sentence `<host> was unreachable at evidence time: read K_H and N_H for it in step 2.`
- Criteria map and `A` grade with §6's rule. A criterion is `met` only when every mapped item is green, `human_pending` when the rest wait on the owner or the activation, and `unmet` otherwise.

- [ ] **Step 1: Confirm red**

Run: `grep -c '^## Human gate$' .agents/artifacts/evidence/cutover-130-checklist.md; test -e .agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md; echo $?`. Expected: `0`, then `1`.

- [ ] **Step 2: After-snapshot**

On each host reachable in Task 1, re-read the registry (C1.d's command) into `SCR/<H>/registry-after.json` and take its `shasum -a 256`. For each roster root, run this script, as Task 1 did: `/bin/bash SCR/rev.sh R` locally, or `ssh … H -- /bin/bash -s -- R < SCR/rev.sh` remotely.

```bash
#!/bin/bash
# rev.sh ROOT: prints HEAD, branch and dirty count, tab-separated
R=$1
h=$(git --no-optional-locks -C "$R" rev-parse HEAD) || exit 1
b=$(git --no-optional-locks -C "$R" symbolic-ref --short -q HEAD || echo detached)
n=$(git --no-optional-locks -C "$R" status --porcelain | wc -l | tr -d ' ')
printf '%s\t%s\t%s\n' "$h" "$b" "$n"
```

Add the two columns. For each changed value, find the cause:
- for a HEAD, `git --no-optional-locks -C R log --format='%h %an %cI %s' <before>..<after>`;
- for a registry, the entries added or removed.

Write `Snapshot:` under the roster. It says either that nothing changed between Task 1 and now, or it lists each change and its cause. It ends with the statement that this attempt committed only on the delivery branch and wrote no roster root or registry (§6 item 4).

- [ ] **Step 3: Summary, window and readiness**

- Write `## Summary` with the table `| ID | Predicate | Source | Phase | Verdict | Disposition |`. It has 18 rows: C1–C12, then P1–P6, with the predicates and sources of spec §3.
- Disposition is the issue numbers from `## Dispositions` for a red item, `owner: gate step 1` for C6 or C7 when human-pending through `migrate`, `owner: host online` for rows human-pending on an unreachable host, `—` for green, and `post-activation` for P rows.
- Compute the window from every row's UTC, and write the two header lines.

- [ ] **Step 4: Post-activation items**

Close `## Evidence` with `### P1–P6 — Post-activation items`. It holds one sentence saying they are `post` and `human-pending`, not evaluated here, and judged at gate step 5 with the evidence in the spec's §3 post-activation table, followed by the table `| ID | Predicate |` with the six predicates from that table.

- [ ] **Step 5: The human gate**

Write `## Human gate`, transcribing spec §5 in order: the intro paragraph (with `<candidate>` and the step-2 re-read of `N_H`) and the headings `### 1. Migrate the ledgers`, `### 2. Re-run the checklist`, `### 3. Freeze`, `### 4. Activation`, `### 5. Post-activation verification`, `### 6. Rollback`. Bind the values:
- step 1 has one fenced pair of lines per roster root, under its host, for example `workflow-state migrate --repo-root /Users/anis/Projects/argus` then the same with `--apply`;
- step 4 has §5's four lines per reachable host, with `K_H` substituted;
- step 5 has `conformance run --purpose doctor --repo-root R` per root;
- step 6 has, per darwin host, `sudo /nix/var/nix/profiles/system-<N>-link/sw/bin/darwin-rebuild --switch-generation <N>`, with `N` from that host's `Generation`. The NixOS host takes §5's two NixOS lines.

Keep §5's prose: the schema-11 sentence, the rewind rule, the mixed-fleet rollback rule, and the after-rollback C12 re-run.

- [ ] **Step 6: Criteria map**

Write `## Criteria map`, with `| AC | Criterion | Items | Verdict |` and rows AC1–AC10. The items are:
- AC1: C2, C3, C5, C6, C8, C10;
- AC2: P1;
- AC3: P2, C12;
- AC4: P3;
- AC5: P6;
- AC6: C1;
- AC7: C6, C7;
- AC8: P2;
- AC9: C9, P3;
- AC10: P5.

Each verdict uses §6's rule, written with the tokens `met`, `unmet` or `human_pending`.

- [ ] **Step 7: The acceptance record**

Create `A` with the line `# Acceptance record — issue #130`, one sentence naming host `mbp`, the evidence window and `CL`, and the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`. It has rows AC1–AC10:
- `Criterion` is the issue's checkbox line, verbatim without the checkbox. AC1–AC5 come from `## Acceptance criteria`, and AC6–AC10 from `### Additional acceptance criteria`.
- `Kind` and `Check or command` come from the plan's Acceptance map.
- For an `evidence (classified)` row: `Observed` is the mapped item verdicts with their `CL` section names; `Commit` is the 40-hex commit that holds the deciding sections (Task 1's for AC6, Task 4's for AC7, and this task's parent for AC1); `Conditions` names the reachable hosts and `origin/main`'s commit.
- For a `human (classified)` row, the three evidence cells are `—`.
- `Verdict` is the criteria-map verdict. sdd's final review owns it.

- [ ] **Step 8: Verify**

```bash
set -e
CL=.agents/artifacts/evidence/cutover-130-checklist.md
A=.agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md
test "$(wc -c < "$CL")" -le 57344
test "$(wc -c < "$A")" -le 10240
test "$(grep '^## ' "$CL" | tr '\n' '/')" = '## Summary/## Roster/## Evidence/## Dispositions/## Human gate/## Criteria map/'
python3 -I - "$CL" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read() + "\n## "
def section(h): return text.split(f"\n## {h}\n", 1)[1].split("\n## ", 1)[0]
def table(body, first):
    return [[x.strip() for x in re.split(r"(?<!\\)\|", l.strip())[1:-1]] for l in body.splitlines()
            if l.startswith("| ") and not l.startswith(f"| {first} |")]
items = {m.group(1): re.search(r"Item verdict: \*\*(\S+)\*\*", m.group(0)).group(1)
         for m in re.finditer(r"^### (C\d+) — .*?(?=^##)", text, re.M | re.S)}
summary = {r[0]: r for r in table(section("Summary"), "ID")}
assert list(summary) == [f"C{n}" for n in range(1, 13)] + [f"P{n}" for n in range(1, 7)], list(summary)
for i, v in items.items():
    assert summary[i][4] == v and summary[i][3] == "pre", i
for n in range(1, 7):
    assert summary[f"P{n}"][3:5] == ["post", "human-pending"], n
bad = {v: sum(x == v for x in items.values()) for v in ("red", "human-pending", "green")}
want = ("Activation readiness: all 12 pre-activation items green" if bad["green"] == 12 else
        f"Activation readiness: activation not permitted — {bad['red']} red, {bad['human-pending']} human-pending, {bad['green']} green of 12")
assert want in text, want
times = re.findall(r"\| (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) \|", text)
assert f"Evidence window: {min(times)} to {max(times)}" in text
gate = section("Human gate")
for n, h in enumerate(["Migrate the ledgers", "Re-run the checklist", "Freeze", "Activation",
                       "Post-activation verification", "Rollback"], 1):
    assert f"\n### {n}. {h}" in gate, h
assert set(re.findall(r"<[a-z_]+>", gate)) == {"<candidate>"}, set(re.findall(r"<[a-z_]+>", gate))
hosts = table(section("Roster").split("### Hosts", 1)[1].split("### Projects", 1)[0], "Host")
for h in hosts:
    if h[1].lower().startswith("yes") and h[6] != "none found":
        assert f"git -C {h[6]} worktree add --detach {h[6]}/.worktrees/cutover-130 <candidate>" in gate, h[0]
        n = h[2].removeprefix("system-")
        assert (f"system-{n}-link/sw/bin/darwin-rebuild --switch-generation {n}" in gate or
                f"nix-env --profile /nix/var/nix/profiles/system --switch-generation {n}" in gate), h[0]
    else:
        assert f"{h[0]} was unreachable at evidence time" in gate or h[6] == "none found", h[0]
for p in table(section("Roster").split("### Projects", 1)[1], "Host"):
    assert f"workflow-state migrate --repo-root {p[2]} --apply" in gate, p[2]
cmap = table(section("Criteria map"), "AC")
assert [r[0] for r in cmap] == [f"AC{n}" for n in range(1, 11)] and all(r[3] in ("met", "unmet", "human_pending") for r in cmap)
print("checklist ok")
EOF
acceptance-record reobserve --record "$A" --head "$(git rev-parse HEAD)"
```

Expected: `checklist ok`, then `{"acceptance_state":…,"changed":[]}` with exit 0. Before Step 3 the heading test fails.
Then rerun Task 1's seam: `adopt-project verify --repo-root "$PWD"` names no `.md` path in any failed `detail`, and `conformance run --purpose doctor --repo-root "$PWD"` is `passed`.

- [ ] **Step 9: Commit**

```bash
git add .agents/artifacts/evidence/cutover-130-checklist.md .agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T6): summary, gate, criteria map, acceptance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Verify: `git status --short -- .agents/artifacts` prints nothing.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":6,"records":[{"bounds":[{"added_lines":450,"boundary":"all","deleted_lines":20,"record_bytes":62720,"support":{"covers":["r1-1","r2-1","r3-1","r4-1","r5-1","r6-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6-1","last_task":6,"owner":6,"path":".agents/artifacts/evidence/cutover-130-checklist.md"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":0,"record_bytes":11520,"support":{"covers":["r6-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r6-2","last_task":6,"owner":6,"path":".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.acceptance.md"}]}}
```
