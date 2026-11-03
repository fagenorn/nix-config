# Task 7: Suite-wide acceptance evidence

Per D6, D7 and D8. This task changes no repository file. It runs the whole suite, the Nix build and the coverage proof once at head, and it collects per-module timings and spawn counts at `BASE` and at head into `${TMPDIR:-/tmp}`. The ship phase records those in the PR description and repeats the wall-time pair on an idle machine. A failure here is reported with its module and log path, never fixed in this task: the fix belongs to the task that owns the failing file.

**Files:**
- None in the repository. Logs go to `${TMPDIR:-/tmp}/issue262-accept/`.

**Interfaces:**
- Consumes: the root's coverage gate and timing driver (verbatim), the `agent-workflow-tests` and `build` recipes, and `BASE` `31be7292b40159c5a3f49cc24f21b3292ba4ce89`.
- Produces: `base.tsv` and `head.tsv` (per-module rows), `suite.log`, `build.log`, `gate.log` and `summary.txt` under `${TMPDIR:-/tmp}/issue262-accept/`. The ship phase reads these paths.

**Invariants:**
- Nothing is written inside the worktree. `git status --porcelain` is empty after the task, apart from changes that were already present before it.
- No recipe, CI file or launcher is invoked other than `just build` and `just agent-workflow-tests` (per D8: serial only).

- [ ] **Step 1: Prepare**

Run Steps 1–5 in one shell session from the worktree root, so `A` stays set.

```bash
set -euo pipefail
A="${TMPDIR:-/tmp}/issue262-accept"; rm -rf "$A"; mkdir -p "$A/base"
rmdir "$A/base"; git worktree add --detach "$A/base" 31be7292b40159c5a3f49cc24f21b3292ba4ce89
git status --porcelain > "$A/status-before.txt"
```

Write the root's timing driver to `$A/timing.py`, and the root's coverage gate to `$A/gate.sh`.

- [ ] **Step 2: Coverage proof**

Run: `bash "$A/gate.sh" > "$A/gate.log" 2>&1; tail -1 "$A/gate.log"`
Expected: `COVERAGE-GATE-OK 2077 test ids`. Anything else fails the task.

- [ ] **Step 3: Whole suite and build at head**

Run, each with a bounded `timeout`:
- `{ time timeout 3600 just agent-workflow-tests ; } > "$A/suite.log" 2>&1`
- `timeout 3600 just build > "$A/build.log" 2>&1`

Expected:
- `grep -E '^Ran [0-9]+ tests' "$A/suite.log"` prints `Ran 2077 tests in ...`
- the suite log's last status line is `OK`
- `just build` exits 0

A different count, or `FAILED`, fails the task. Report the failing test IDs from the log.

- [ ] **Step 4: Per-module timing and spawns, base then head**

Run back-to-back, each with `timeout 7200`:
- `python3 "$A/timing.py" "$A/base" > "$A/base.tsv"`
- `python3 "$A/timing.py" . > "$A/head.tsv"`

Each driver run exits non-zero when any module failed or reported no test count; its failure logs are under `<tree>.logs/`. Expected: every row's `exit` is `0` in both files, and each module's `tests` count is equal across the two files. Every head row should show `spawns` at or below its base row. A head row above 90 s is reported with its `load1_before` value. It does not fail this task, because the idle-machine 90 s check happens at ship (per D6).

- [ ] **Step 5: Summary**

```bash
python3 - "$A" <<'PY' > "$A/summary.txt"
import csv, sys
A = sys.argv[1]
rows = {name: list(csv.DictReader(open(f"{A}/{name}.tsv"), delimiter="\t")) for name in ("base", "head")}
base = {r["module"]: r for r in rows["base"]}
print("module\ttests\tbase_s\thead_s\tbase_spawns\thead_spawns\thead_load1\tbase_exit\thead_exit")
for r in rows["head"]:
    b = base[r["module"]]
    print("\t".join([r["module"], r["tests"], b["wall_s"], r["wall_s"], b["spawns"], r["spawns"], r["load1_before"], b["exit"], r["exit"]]))
PY
cat "$A/summary.txt" | tail -5
test -z "$(diff <(git status --porcelain) "$A/status-before.txt")"
```

Remove the disposable baseline checkout with `git worktree remove --force "$A/base"` (it is the scratch checkout Step 1 created, never another worktree).

Report the `summary.txt` path, the `TOTAL` rows, the suite's `real` time from `suite.log`, and any head module over 90 s with its load. Do not paste the whole table.
