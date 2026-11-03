# Task 3: Candidate, bundle and deprecated-path users

This task covers the spec §3 rows C3, C4 and C11, and follows D8 and D11. It adds three item sections to `CL`, which feed AC1's check (C3).

**Files:**
- Modify: `.agents/artifacts/evidence/cutover-130-checklist.md` (`CL`)

**Interfaces:**
- Consumes: Task 1's roster; Task 2's C2 section (the C2.a rows' intervals, cited by C4); `origin/main` in the delivery worktree, as last fetched, never fetched (D15).
- Produces: `### C3 — Approved bundle binds the candidate`, `### C4 — Candidate and bridge fleet preflight`, and `### C11 — Deprecations shipped, zero users`, placed in numeric order after C2 and C10 respectively.

**Invariants:**
- The task is read-only, per Global Constraints, and `CL` is its only write. Sections written earlier keep their bytes.
- No candidate exists in this attempt (D1), so C3 and C4 are red unless this run finds a manifest at `2.0.0` or above. Neither can be green by inference (D4, D11).
- C11 is fail-closed. A root whose contract does not resolve is red, with the resolver's `error.code`, because zero users cannot be shown.

- [ ] **Step 1: Confirm red**

Run: `grep -c '^### C11 — ' .agents/artifacts/evidence/cutover-130-checklist.md`. Expected: `0`, exit 1.

- [ ] **Step 2: C3**

```text
C3.a git ls-tree --name-only origin/main -- .agents/artifacts/evidence/
C3.b git show origin/main:<path>
```

Run C3.a in the delivery worktree, and keep the names ending in `-bundle.json`. For each, run C3.b and read `state` and `identity.bound.commit.candidate`. Write one row per bundle: host `mbp`, subject the path, revision `origin/main`'s 12-hex, Observed `state <s>; candidate <12-hex>`. A row is green only when `state` is `approved` and the candidate is the commit C4 names as the strict candidate. Today C4 names none, so every row is red. When there is no bundle, write one red row, subject `.agents/artifacts/evidence/`, Observed `no *-bundle.json`. Planning saw `promotion-127-bundle.json` and `release-128-bundle.json`, both `unmeasured`.

- [ ] **Step 3: C4**

```text
C4.a git show origin/main:home/common/agent-skills/platform-manifest.json
```

Read `platform_version`, `deprecations` and `removals`, then cite the intervals of the C2.a host rows. Write one row: host `mbp`, subject `home/common/agent-skills/platform-manifest.json`, revision `origin/main`'s 12-hex, Observed `platform_version 1.0.0; every C2.a interval [1.0.0,2.0.0)` (as observed). It is red when `platform_version` is below `2.0.0` or any C2.a interval excludes `2.0.0`, which is the strict major #66 requires. Otherwise the candidate exists, and the row stays red with Observed `candidate present: re-plan` while you return `BLOCKED candidate_present`, because D1 assumes none.

- [ ] **Step 4: C11**

```text
C11.a resolve-project platform-status
C11.b git --no-optional-locks -C R ls-files -- .claude/skills.config.json
C11.c resolve-project resolve --repo-root R
C11.d git --no-optional-locks -C R grep -n -F 'release deploy inspect' -- . ':!.agents/artifacts'
```

- Run C11.a once per reachable host (timeout 120 s). The host row is red when `platform.deprecations` is empty, because the candidate removes the legacy file, its writer, `bindings.deploy` and `release deploy inspect` without a declared deprecation (D8). Otherwise it is green, with the entries counted.
- Run C11.b–d per root (timeout 120 s each). For `fagenorn/nix-config`, C11.d's pathspec is `home/common/agent-skills/skills` instead of `. ':!.agents/artifacts'`, because that root's implementation and tests are what the candidate deletes. Run C11.b–d through one script, `SCR/c11.sh`: locally as `/bin/bash SCR/c11.sh R <pathspec…>`, and remotely as `ssh … H -- /bin/bash -s -- R <pathspec…> < SCR/c11.sh`. Save its output to `SCR/<H>/<project>-c11.txt`, and read `bindings.deploy.adapter` from the C11.c block, or the refusal's `error.code`.

```bash
#!/bin/bash
# c11.sh ROOT PATHSPEC...: C11.b, C11.c and C11.d for one root, each block headed by its label
R=$1; shift
echo "== C11.b"; git --no-optional-locks -C "$R" ls-files -- .claude/skills.config.json; echo "== exit $?"
echo "== C11.c"; resolve-project resolve --repo-root "$R"; echo "== exit $?"
echo "== C11.d"; git --no-optional-locks -C "$R" grep -n -F 'release deploy inspect' -- "$@"; echo "== exit $?"
```
- A root row is red for any of: C11.b lists the file; the adapter is not `none`; C11.c refuses; C11.d prints a hit. `git grep` exiting 1 with no output means no hit. Observed reads like `legacy file tracked; deploy.adapter railway; 0 hits`. When a list is too long, count the hits there.
- Point-in-time records under `.agents/artifacts` are excluded by the pathspec and are not users.
- Planning saw Arcwave and Nodo tracking the legacy file, Nodo's adapter `railway`, JarBird's `github-actions-health`, and nix-config `none` with 0 hits. Record what this run observes.

- [ ] **Step 5: Write the sections**

Insert C3 and C4 after C2, and C11 after C10, in the Global Constraints item format. The `> ` lines are:
- C3: "a fresh `approved` evidence bundle from the token-gate instrument covers the strict-cutover candidate as a whole";
- C4: #71's "candidate and retained-bridge fleet preflight green for every registered project";
- C11: "Deprecation notices shipped in the bridge minor; removal happens only here, in the major, and only after zero fleet users of the deprecated paths."

- [ ] **Step 6: Verify**

```bash
set -e
CL=.agents/artifacts/evidence/cutover-130-checklist.md
test "$(wc -c < "$CL")" -le 30720
test "$(grep -n '^### C' "$CL" | cut -d' ' -f2 | tr '\n' ' ')" = 'C1 C2 C3 C4 C8 C9 C10 C11 C12 '
python3 -I - "$CL" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read() + "\n## "
roster = text.split("### Projects", 1)[1].split("\n## ", 1)[0]
rows = [[x.strip() for x in c.strip().strip("|").split("|")] for c in roster.splitlines()
        if c.startswith("| ") and not c.startswith("| Host |")]
c11 = re.search(r"^### C11 — .*?(?=^##)", text, re.M | re.S).group(0)
for cells in rows:
    assert f"| {cells[0]} | {cells[2]} |" in c11, f"C11: no row for {cells[0]} {cells[2]}"
for item in ("C3", "C4"):
    body = re.search(rf"^### {item} — .*?(?=^##)", text, re.M | re.S).group(0)
    assert "Item verdict: **red**" in body, item + " must be red while no candidate exists (D11)"
print("coverage ok")
EOF
```

Then, in one Bash call, run `export CHECK_ITEMS='C3 C4 C11'` followed by the root's row check.
Expected: `coverage ok`, then `rows ok`. Before Step 5 the heading-order test fails.

- [ ] **Step 7: Commit**

```bash
git add .agents/artifacts/evidence/cutover-130-checklist.md
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T3): candidate, bundle, deprecated-path users" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Verify: `git status --short -- .agents/artifacts/evidence` prints nothing.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":0,"record_bytes":33280,"support":{"covers":["r1-1","r2-1","r3-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3-1","last_task":6,"owner":3,"path":".agents/artifacts/evidence/cutover-130-checklist.md"}]}}
```
