# Task 4: Legacy release, ledgers and worktrees

This task covers the spec §3 rows C5, C6 and C7, and follows D9 and D15. It holds AC7's check and adds three item sections to `CL`. These rows read persisted lifecycle state in five fleet roots and must not disturb it.

**Files:**
- Modify: `.agents/artifacts/evidence/cutover-130-checklist.md` (`CL`)

**Interfaces:**
- Consumes: Task 1's roster.
- Produces: `### C5 — No legacy release in flight`, `### C6 — Legacy ledgers have a strict-path mapping` and `### C7 — Retained worktrees have a strict-path mapping`, placed in numeric order after C4.

**Invariants:**
- The task is read-only, per Global Constraints. `workflow-state migrate` runs without `--apply`, and no worktree is listed with `prune`, added or removed. `CL` is the only write, and sections written earlier keep their bytes.
- C7 classes each linked worktree in exactly one class, from the C6 verdicts of the ledgers whose `state.json` holds its path as a whole JSON string (D15):
  - `current`: some ledger is `current` or `migrated`;
  - `migrate`: otherwise, some ledger is `migrate`;
  - `refused-only`: otherwise, the path is in at least one ledger;
  - `unmapped`: it is in none.

  A ledger directory that C6 does not list counts as refused.

- [ ] **Step 1: Confirm red**

Run: `grep -c '^### C6 — ' .agents/artifacts/evidence/cutover-130-checklist.md`. Expected: `0`, exit 1.

- [ ] **Step 2: C5**

```text
C5.a ls -la R/.superpowers/workflows/ship-release/state.json
C5.b release transaction status --repo-root R
```

Run C5.a per root (timeout 60 s). When it reports `No such file or directory`, the row is green, Observed `absent`. When the file exists, run C5.b and read `legacy.class`:
- `completed` is green;
- `in_flight` or `unreadable` is red;
- a refusal, such as an unsupported release capability, is red with its message (#90; D6).

- [ ] **Step 3: C6**

```text
C6.a workflow-state migrate --repo-root R
```

Run per root without `--apply` (timeout 300 s), saving to `SCR/<H>/<project>-migrate.json`. Read `counts` (`current`, `migrate`, `migrated`, `refused`). The row is:
- red when `refused` > 0, with Observed giving the counts and the refused reasons tallied (for example `refused 6 (invalid_state 6)`);
- otherwise human-pending when `migrate` > 0, cleared by the owner's gate step 1;
- green when every ledger is `current` or `migrated` (D9).

Planning's dry runs refused ledgers in nix-config, Argus, Arcwave and Nodo. Record what this run observes.

- [ ] **Step 4: C7**

```text
C7.a git --no-optional-locks -C R worktree list --porcelain
C7.b grep -l -F -e '"<path>"' -e '"<realpath>"' R/.superpowers/workflows/*/state.json
```

Write `SCR/c7.sh` and run it per root: locally as `/bin/bash SCR/c7.sh R > SCR/<H>/<project>-c7.tsv`, and remotely as `ssh … H -- /bin/bash -s -- R < SCR/c7.sh` (timeout 300 s).

```bash
#!/bin/bash
# c7.sh ROOT: one line per linked worktree: path<TAB>ledger directory names
R=$1
git --no-optional-locks -C "$R" worktree list --porcelain | sed -n 's/^worktree //p' | tail -n +2 |
while IFS= read -r P; do
  RP=$(cd "$P" 2>/dev/null && pwd -P || printf '%s' "$P")
  L=$(grep -l -F -e "\"$P\"" -e "\"$RP\"" "$R"/.superpowers/workflows/*/state.json 2>/dev/null |
      awk -F/ '{print $(NF-1)}' | sort -u | tr '\n' ' ')
  printf '%s\t%s\n' "$P" "$L"
done
```

The first `worktree` entry is the main checkout and is skipped. Classify each line with the C6 JSON of the same root:

```bash
python3 -I - SCR/<H>/<project>-migrate.json SCR/<H>/<project>-c7.tsv <<'EOF'
import json, sys
verdict = {l["ledger"]: l["verdict"] for l in json.load(open(sys.argv[1]))["ledgers"]}
classes = {"current": 0, "migrate": 0, "refused-only": 0, "unmapped": 0}
for line in open(sys.argv[2], encoding="utf-8"):
    path, _, names = line.rstrip("\n").partition("\t")
    found = {verdict.get(n, "refused") for n in names.split()}
    if not found: c = "unmapped"
    elif found & {"current", "migrated"}: c = "current"
    elif "migrate" in found: c = "migrate"
    else: c = "refused-only"
    classes[c] += 1
    print(c, path, sep="\t")
print(json.dumps(classes), file=sys.stderr)
EOF
```

The row is:
- red when `refused-only` + `unmapped` > 0;
- otherwise human-pending when `migrate` > 0;
- otherwise green, including a root with no linked worktree.

Observed is the class counts, for example `worktrees 138: current 0, migrate 12, refused-only 3, unmapped 123`. Task 5 re-runs this script and classifier to get the per-path list for its filing. The counts include the delivery worktree: this run creates no worktree (§3), and its own worktree maps to its ledger.

- [ ] **Step 5: Write the sections**

Insert C5, C6 and C7 after C4, in the Global Constraints item format. C5 quotes "no legacy release is in flight" (#90). C6 quotes "Do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping", and C7 quotes the same sentence for worktrees.

- [ ] **Step 6: Verify**

```bash
set -e
CL=.agents/artifacts/evidence/cutover-130-checklist.md
test "$(wc -c < "$CL")" -le 40960
test "$(grep -n '^### C' "$CL" | cut -d' ' -f2 | tr '\n' ' ')" = 'C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12 '
python3 -I - "$CL" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read() + "\n## "
roster = text.split("### Projects", 1)[1].split("\n## ", 1)[0]
rows = [[x.strip() for x in c.strip().strip("|").split("|")] for c in roster.splitlines()
        if c.startswith("| ") and not c.startswith("| Host |")]
for item in ("C5", "C6", "C7"):
    body = re.search(rf"^### {item} — .*?(?=^##)", text, re.M | re.S).group(0)
    for cells in rows:
        assert f"| {cells[0]} | {cells[2]} |" in body, f"{item}: no row for {cells[0]} {cells[2]}"
c7 = re.search(r"^### C7 — .*?(?=^##)", text, re.M | re.S).group(0)
assert re.search(r"refused-only \d+, unmapped \d+", c7), "C7: class counts missing"
print("coverage ok")
EOF
```

Then, in one Bash call, run `export CHECK_ITEMS='C5 C6 C7'` followed by the root's row check.
Expected: `coverage ok`, then `rows ok`. Before Step 5 the heading-order test fails.

- [ ] **Step 7: Commit**

```bash
git add .agents/artifacts/evidence/cutover-130-checklist.md
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T4): legacy release, ledgers, worktrees" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Verify: `git status --short -- .agents/artifacts/evidence` prints nothing.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":4,"records":[{"bounds":[{"added_lines":320,"boundary":"all","deleted_lines":0,"record_bytes":43520,"support":{"covers":["r1-1","r2-1","r3-1","r4-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-1","last_task":6,"owner":4,"path":".agents/artifacts/evidence/cutover-130-checklist.md"}]}}
```
